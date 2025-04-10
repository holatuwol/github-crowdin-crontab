#!/usr/bin/env python

import binascii
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
    "ja_JP": 'ご覧のページは、お客様の利便性のために一部機械翻訳されています。また、ドキュメントは頻繁に更新が加えられており、翻訳は未完成の部分が含まれることをご了承ください。最新情報は都度公開されておりますため、必ず英語版をご参照ください。翻訳に問題がある場合は、 <a href="mailto:support-content-jp@liferay.com">こちら</a> までご連絡ください。'
}

env = load_dotenv()

learn_domain = os.getenv("learn_domain")
learn_group_id = os.getenv("learn_group_id")
learn_scratch_dir = os.getenv("learn_scratch_dir")

access_token = None
access_token_expires = None

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

    params = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }

    r = session.post(
        f"https://{learn_domain}/o/oauth2/token",
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

    new_files, all_files, file_info = get_repository_state(
        repository, source_language[:2], target_language[:2]
    )

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
        get_articles_url = f"https://{learn_domain}/o/headless-delivery/v1.0/sites/{learn_group_id}/structured-contents"

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

    # don't upload more than 50 files, because we'll hit quota limits

    crowdin_directory = get_directory(repository, "", False)

    if crowdin_directory is not None:
        delete_url = "/projects/%s/directories/%s" % (
            repository.project_id,
            crowdin_directory["id"],
        )

        status_code, response_data = crowdin_request(delete_url, "DELETE")

    crowdin_upload_sources(
        repository, source_language[:2], target_language[:2], outdated_articles[:50]
    )

    os.chdir(old_dir)

    return outdated_articles


def copy_local_to_learn(source_language, target_language):
    outdated_articles = get_outdated_articles(target_language)

    old_dir = os.getcwd()
    os.chdir(learn_scratch_dir)

    for html_file in outdated_articles:
        article_id = html_file[html_file.rfind("/") + 1 : -5]
        publish_target_content(article_id, source_language, target_language)

    os.chdir(old_dir)


def get_outdated_articles(language):
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
    headless_headers["Accept-Language"] = accept_language.replace("_", "-")

    if method == "GET":
        r = session.get(url, params=data, headers=headless_headers)
    elif method == "PATCH":
        r = requests.patch(url, json=data, headers=headless_headers)
    elif method == "PUT":
        r = requests.put(url, json=data, headers=headless_headers)
    else:
        raise Exception("Unrecognized method: %s" % method)

    try:
        return r.status_code, r.json()
    except:
        return r.status_code, r.text


def publish_target_content(article_id, source_language, target_language):
    update_article_url = f"https://{learn_domain}/o/headless-delivery/v1.0/structured-contents/{article_id}"

    html_file = "%s/%s.html" % (target_language[:2], article_id)

    with open(html_file, "r", encoding="utf-8") as f:
        html_content = f.read()

    update_content = html_content

    if target_language in disclaimer:
        update_content = '<div class="adm-block adm-note">%s</div>%s' % (
            disclaimer[target_language],
            html_content,
        )

    json_file = "%s/%s.json" % (source_language[:2], article_id)

    with open(json_file, "r", encoding="utf-8") as f:
        params = json.load(f)

    available_languages = params["availableLanguages"]

    keys = [key for key in params]
    for key in keys:
        if key not in ["contentFields", "contentStructureId", "title"]:
            del params[key]

    for field in params["contentFields"]:
        keys = [key for key in field]
        for key in keys:
            if key not in ["contentFieldValue", "name"]:
                del field[key]

    content_field = [
        field for field in params["contentFields"] if field["name"] == "content"
    ][0]
    content_field["contentFieldValue"]["data"] = update_content

    if target_language in available_languages:
        logging.info(
            "Updating translation to %s on article %s" % (target_language, article_id)
        )

        status_code, response_data = make_headless_request(
            update_article_url, "PATCH", target_language, params
        )
    else:
        logging.info(
            "Adding translation to %s on article %s" % (target_language, article_id)
        )
        logging.info(json.dumps(params))

        status_code, response_data = make_headless_request(
            update_article_url, "PUT", target_language, params
        )

    if status_code == 200:
        with open("%s.crc32" % html_file, "w", encoding="utf-8") as f:
            f.write(str(binascii.crc32(html_content.encode("utf-8"))))
    else:
        raise Exception(f"{response_data} (error code {status_code})")


def translate_learn_on_crowdin(source_language, target_language):
    outdated_articles = get_outdated_articles(source_language)

    repository = get_repository(learn_domain)

    new_files, all_files, file_info = get_repository_state(
        repository, source_language[:2], target_language[:2]
    )

    old_dir = os.getcwd()
    os.chdir("%s/%s" % (learn_scratch_dir, source_language[:2]))

    pre_translate(
        repository,
        source_language[:2],
        target_language[:2],
        outdated_articles,
        file_info,
    )

    os.chdir(old_dir)


if __name__ == "__main__":
    try:
        actions = set(sys.argv[1:])

        if "sync" in actions:
            copy_learn_to_local("en_US")

        if "upload" in actions:
            copy_local_to_crowdin("en_US", "ja_JP")

        if "translate" in actions:
            translate_learn_on_crowdin("en_US", "ja_JP")

        if "download" in actions:
            copy_crowdin_to_local("en_US", "ja_JP")

        if "publish" in actions:
            copy_local_to_learn("en_US", "ja_JP")
    finally:
        save_session()
