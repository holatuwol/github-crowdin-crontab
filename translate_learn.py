#!/usr/bin/env python

import binascii

from bs4 import BeautifulSoup
from crowdin import (
    crowdin_download_translations,
    crowdin_upload_sources,
    extract_crowdin_translation,
    pre_translate,
)
from crowdin_util import (
    crowdin_request,
    get_directory,
    get_repository,
    get_repository_state,
)
import datetime
from dotenv import load_dotenv
import json
import logging
import onepass
import os
import requests
from session import session
from session import save_session
import sys

disclaimer = {
    "ja-JP": 'ご覧のページは、お客様の利便性のために一部機械翻訳されています。また、ドキュメントは頻繁に更新が加えられており、翻訳は未完成の部分が含まれることをご了承ください。最新情報は都度公開されておりますため、必ず英語版をご参照ください。翻訳に問題がある場合は、 <a href="mailto:support-content-jp@liferay.com">こちら</a> までご連絡ください。'
}

env = load_dotenv()

learn_domain = os.getenv("learn_domain")
learn_group_id = os.getenv("learn_group_id")
learn_scratch_dir = os.getenv("learn_scratch_dir")

learn_url = (
    f"http://{learn_domain}"
    if learn_domain == "localhost:8080"
    else f"https://{learn_domain}"
)

access_token = None
access_token_expires = None
use_i18n_put_for_update = True

headers = {
    "Accept": "application/json",
    "User-Agent": "translate_learn.py",
}


def authorize():
    global access_token, access_token_expires

    if access_token is not None and datetime.datetime.now() < access_token_expires:
        return

    client_id = onepass.item("OAuth2 %s" % os.getenv("learn_domain"), "username")[
        "username"
    ]
    client_secret = onepass.item("OAuth2 %s" % os.getenv("learn_domain"), "credential")[
        "credential"
    ]

    if len(client_id) == 0 or len(client_secret) == 0:
        return

    params = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }

    r = session.post(
        f"{learn_url}/o/oauth2/token",
        data=params,
        headers={"User-Agent": "translate_learn.py"},
    )
    response_json = r.json()

    access_token = response_json["access_token"]
    access_token_expires = datetime.datetime.now() + datetime.timedelta(
        seconds=response_json["expires_in"]
    )

    headers["Authorization"] = f"Bearer {access_token}"


def copy_crowdin_to_local(source_language, target_language):
    outdated_articles = get_outdated_articles(source_language)

    repository = get_repository(learn_domain)

    _, file_info = get_repository_state(repository, target_language[:2])

    old_dir = os.getcwd()
    os.chdir(learn_scratch_dir)

    export_file_name = crowdin_download_translations(
        repository,
        source_language[:2],
        target_language[:2],
        outdated_articles,
        file_info,
    )

    extract_crowdin_translation(
        repository, export_file_name, source_language[:2], source_language[:2]
    )

    os.chdir(old_dir)


def copy_learn_to_local(language):
    language_folder = "%s/%s" % (learn_scratch_dir, language[:2])
    os.makedirs(language_folder, exist_ok=True)

    last_search_time = "1970-01-01T00:00:00Z"

    timestamp_file = "%s/.timestamp" % language_folder

    if os.path.exists(timestamp_file):
        with open(timestamp_file, "r", encoding="utf-8") as f:
            last_search_time = f.read()

    cache_file = "%s/new_articles.json" % language_folder

    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            new_articles = json.load(f)
    else:
        get_articles_url = f"{learn_url}/o/headless-delivery/v1.0/sites/{learn_group_id}/structured-contents"

        params = {"flatten": "true", "filter": f"dateModified ge {last_search_time}"}

        new_articles = make_headless_list_request(get_articles_url, language, params)

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(new_articles, f)

    print(len(new_articles), "articles modified since", last_search_time)

    for article in new_articles:
        fields = article["contentFields"]
        content_fields = [field for field in fields if field["name"] == "content"]

        if len(content_fields) == 0:
            continue

        del article["actions"]

        with open(
            "%s/%s.json" % (language_folder, article["id"]), "w", encoding="utf-8"
        ) as f:
            json.dump(article, f)

        content = content_fields[0]["contentFieldValue"]["data"]

        with open(
            "%s/%s.html" % (language_folder, article["id"]), "w", encoding="utf-8"
        ) as f:
            f.write(content)

    last_search_time = max([article["dateModified"] for article in new_articles])

    os.remove(cache_file)

    with open(timestamp_file, "w", encoding="utf-8") as f:
        f.write(last_search_time)


def copy_local_to_crowdin(source_language, target_language):
    repository = get_repository(learn_domain)

    outdated_articles = get_outdated_articles(source_language)

    old_dir = os.getcwd()
    os.chdir("%s/%s" % (learn_scratch_dir, source_language[:2]))

    crowdin_directory = get_directory(repository, "", False)

    if crowdin_directory is not None:
        delete_url = "/projects/%s/directories/%s" % (
            repository.project_id,
            crowdin_directory["id"],
        )

        status_code, response_data = crowdin_request(delete_url, "DELETE")

        logging.error(status_code)
        logging.error(response_data)

    if len(outdated_articles) == 0:
        return False

    # don't upload more than 50 files, because we'll hit quota limits

    crowdin_upload_sources(
        repository, source_language[:2], target_language[:2], outdated_articles[:50]
    )

    os.chdir(old_dir)

    return True


def copy_local_to_learn(source_language, target_language):
    outdated_articles = get_outdated_articles(target_language)

    old_dir = os.getcwd()
    os.chdir(learn_scratch_dir)

    for html_file in outdated_articles:
        article_id = html_file[html_file.rfind("/") + 1 : -5]
        publish_target_content(article_id, source_language, target_language)

    os.chdir(old_dir)


def get_outdated_articles(language):
    # if True:
    #     return ["ja/33237462.html", "ja/34607584.html"]

    language_folder = "%s/%s" % (learn_scratch_dir, language[:2])
    outdated_articles = []

    if not os.path.exists(language_folder):
        print(len(outdated_articles), "out of date files")

        return outdated_articles

    for html_file_name in [
        file for file in os.listdir(language_folder) if file[-5:] == ".html"
    ]:
        html_file = "%s/%s" % (language_folder, html_file_name)
        hash_file = "%s.crc32" % html_file

        if not os.path.exists(hash_file):
            outdated_articles.append(html_file_name)
            continue

        with open(hash_file, "r", encoding="utf-8") as f:
            old_hash = f.read()

        with open(html_file, "rb") as f:
            new_hash = str(binascii.crc32(f.read()))

        if old_hash != new_hash:
            outdated_articles.append(html_file_name)

    print(len(outdated_articles), "out of date files")

    return outdated_articles


def make_headless_list_request(url, accept_language, initial_params):
    params = initial_params.copy()

    params["page"] = 1
    params["pageSize"] = 100
    params["sort"] = "dateModified"

    status_code, response_json = make_headless_request(
        url, "GET", accept_language, params
    )

    items = response_json["items"]
    page_number = 1

    while len(items) < response_json["totalCount"]:
        page_number = page_number + 1

        params["page"] = page_number
        print(
            f'{url} ({(page_number - 1) * 100} of {response_json["totalCount"]} results already seen)'
        )

        status_code, response_json = make_headless_request(
            url, "GET", accept_language, params
        )

        items.extend(response_json["items"])

        params["page"] = page_number

    return items


def make_headless_request(url, method, accept_language, data):
    authorize()

    headless_headers = headers.copy()
    headless_headers["Accept-Language"] = accept_language

    if method == "GET":
        r = session.get(url, params=data, headers=headless_headers)
    elif method == "PATCH":
        r = requests.patch(url, json=data, headers=headless_headers)
    elif method == "PUT":
        r = requests.put(url, json=data, headers=headless_headers)
    else:
        raise Exception("Unrecognized method: %s" % method)

    print(f"{method} {url} ({r.status_code})")

    try:
        return r.status_code, r.json()
    except:
        return r.status_code, r.text


def publish_target_content(article_id, source_language, target_language):
    html_file = "%s/%s.html" % (target_language[:2], article_id)

    with open(html_file, "r", encoding="utf-8") as f:
        html_content = f.read()

    update_content = html_content

    if target_language in disclaimer:
        update_content = '<div class="adm-block adm-note">%s</div>%s' % (
            disclaimer[target_language],
            html_content,
        )

    method, params = get_update_params(
        article_id, source_language, target_language, update_content
    )

    if method is None:
        return

    status_code, response_data = make_headless_request(
        f"{learn_url}/o/headless-delivery/v1.0/structured-contents/{article_id}",
        method,
        target_language,
        params,
    )

    if status_code == 200:
        with open("%s.crc32" % html_file, "w", encoding="utf-8") as f:
            f.write(str(binascii.crc32(html_content.encode("utf-8"))))
    else:
        print(
            "failed to publish %s (status code: %d, data: %s)"
            % (html_file, status_code, json.dumps(response_data))
        )


def get_update_params(article_id, source_language, target_language, update_content):
    status_code, source_data = make_headless_request(
        f"{learn_url}/o/headless-delivery/v1.0/structured-contents/{article_id}",
        "GET",
        source_language,
        {},
    )

    if status_code != 200:
        return

    available_languages = source_data["availableLanguages"]
    update_title = source_data["title"]
    update_document = BeautifulSoup(update_content, features="html.parser")

    h1_element = update_document.find(lambda x: x.name.lower() == "h1")
    if h1_element is not None:
        update_title = h1_element.getText()

    if not use_i18n_put_for_update or target_language in available_languages:
        params = {
            "title": update_title,
            "description": source_data["description"],
            "contentFields": [
                {
                    "name": field["name"],
                    "contentFieldValue": {
                        "data": (
                            update_content
                            if field["name"] == "content"
                            else field["contentFieldValue"]["data"]
                        )
                    },
                }
                for field in source_data["contentFields"]
            ],
        }

        return "PATCH" if target_language in available_languages else "PUT", params

    params = json.loads(json.dumps(source_data))
    del params["actions"]

    params["availableLanguages"].append(target_language)

    params["title"] = update_title
    params["title_i18n"] = {source_language: source_data["title"]}
    params["description"] = source_data["description"]
    params["description_i18n"] = {source_language: source_data["description"]}

    for field in params["contentFields"]:
        field["contentFieldValue_i18n"] = {
            source_language: {"data": field["contentFieldValue"]["data"]}
        }

        if field["name"] == "content":
            field["contentFieldValue"]["data"] = update_content

    params_fields = {
        field["name"]: field["contentFieldValue_i18n"]
        for field in params["contentFields"]
    }

    for language in available_languages:
        if language == source_language:
            continue

        status_code, language_data = make_headless_request(
            f"{learn_url}/o/headless-delivery/v1.0/structured-contents/{article_id}",
            "GET",
            language,
            {"fields": "title,description,contentFields"},
        )

        if status_code != 200:
            return None

        params["title_i18n"][language] = language_data["title"]
        params["description_i18n"][language] = language_data["description"]

        for field in language_data["contentFields"]:
            params_fields[field["name"]][language] = {
                "data": field["contentFieldValue"]
            }

    return "PUT", params


def translate_learn_on_crowdin(source_language, target_language):
    repository = get_repository(learn_domain)

    old_dir = os.getcwd()
    os.chdir("%s/%s" % (learn_scratch_dir, source_language[:2]))

    pre_translate(repository, source_language[:2], target_language[:2])

    os.chdir(old_dir)


if __name__ == "__main__":
    try:
        actions = set(sys.argv[1:])

        if "copy_learn_to_local" in actions:
            copy_learn_to_local("en-US")

        if "translate" in actions:
            while True:
                translate_learn_on_crowdin("en-US", "ja-JP")
                copy_crowdin_to_local("en-US", "ja-JP")

                if not copy_local_to_crowdin("en-US", "ja-JP"):
                    break

        if "copy_local_to_learn" in actions:
            copy_local_to_learn("en-US", "ja-JP")
    finally:
        save_session()
