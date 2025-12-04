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
import os
import requests
from session import session
from session import save_session
import sys

batch_size = 200

disclaimer = {
    "ja-JP": 'ご覧のページは、お客様の利便性のために一部機械翻訳されています。また、ドキュメントは頻繁に更新が加えられており、翻訳は未完成の部分が含まれることをご了承ください。最新情報は都度公開されておりますため、必ず英語版をご参照ください。翻訳に問題がある場合は、 <a href="mailto:support-content-jp@liferay.com">こちら</a> までご連絡ください。'
}

env = load_dotenv()

learn_domain = os.getenv("learn_domain")
client_id = os.getenv("client_id")
client_secret = os.getenv("client_secret")
learn_group_id = os.getenv("learn_group_id")
learn_scratch_dir = os.getenv("learn_scratch_dir")

learn_url = (
    f"http://{learn_domain}"
    if learn_domain.find("localhost") != -1
    else f"https://{learn_domain}"
)

access_token = None
access_token_expires = None
use_i18n_put_for_update = True

def authorize():
    global access_token, access_token_expires, client_id, client_secret

    if access_token is not None and access_token_expires is not None and datetime.datetime.now() < access_token_expires:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "translate_learn.py",
        }
    
    if client_id is None or client_id == '' or client_secret is None or client_secret == '':
        return {
            "Accept": "application/json",
            "User-Agent": "translate_learn.py",
        }

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

    print(f"POST {learn_url}/o/oauth2/token ({r.status_code})")

    response_json = r.json()

    access_token = response_json["access_token"]
    access_token_expires = datetime.datetime.now() + datetime.timedelta(
        seconds=response_json["expires_in"]
    )

    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "translate_learn.py",
    }


def copy_crowdin_to_local(source_language, target_language):
    repository = get_repository(learn_domain)

    _, file_info = get_repository_state(repository, target_language[:2])

    old_dir = os.getcwd()
    os.chdir(learn_scratch_dir)

    export_file_name = crowdin_download_translations(
        repository,
        source_language[:2],
        target_language[:2],
        file_info,
    )

    extract_crowdin_translation(
        repository, export_file_name, source_language[:2], target_language[:2]
    )

    os.chdir(old_dir)


def fix_content(content):
    for bad_ch in ['‘', '’', '&rsquo;']:
        content = content.replace(bad_ch, '\'')

    for bad_ch in ['“', '”', '&ldquo;', '&rdquo;']:
        content = content.replace(bad_ch, '"')

    return content

def copy_learn_to_local(language):
    copy_learn_web_content_to_local(language)


def copy_learn_knowledge_articles_to_local(language):
    language_folder = "%s/%s/knowledge_articles" % (learn_scratch_dir, language[:2])
    os.makedirs(language_folder, exist_ok=True)

    last_search_time = "1970-01-01T00:00:00Z"

    timestamp_file = "%s/.timestamp" % language_folder

    if os.path.exists(timestamp_file):
        with open(timestamp_file, "r", encoding="utf-8") as f:
            last_search_time = f.read()

    get_articles_url = f"{learn_url}/o/c/p2s3knowledgearticles/"

    params = {
        "fields": "id,content,title,dateModified",
        "filter": f"dateModified gt {last_search_time}"
    }

    new_articles = make_headless_list_request(get_articles_url, language, params)

    print(len(new_articles), "articles modified since", last_search_time)

    for article in new_articles:
        with open(
            "%s/%s.json" % (language_folder, article["id"]), "w", encoding="utf-8"
        ) as f:
            json.dump(article, f)

        content = article['content']

        with open(
            "%s/%s.html" % (language_folder, article["id"]), "w", encoding="utf-8"
        ) as f:
            f.write(fix_content(content))

    last_search_time = max([article["dateModified"] for article in new_articles])

    with open(timestamp_file, "w", encoding="utf-8") as f:
        f.write(last_search_time)


def copy_learn_web_content_to_local(language):
    language_folder = "%s/%s/web_content" % (learn_scratch_dir, language[:2])
    os.makedirs(language_folder, exist_ok=True)

    last_search_time = "1970-01-01T00:00:00Z"

    timestamp_file = "%s/.timestamp" % language_folder

    if os.path.exists(timestamp_file):
        with open(timestamp_file, "r", encoding="utf-8") as f:
            last_search_time = f.read()

    get_articles_url = f"{learn_url}/o/headless-delivery/v1.0/sites/{learn_group_id}/structured-contents"

    params = {"flatten": "true", "filter": f"dateModified ge {last_search_time}"}

    new_articles = make_headless_list_request(get_articles_url, language, params)

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
            f.write(fix_content(content))

    last_search_time = max([article["dateModified"] for article in new_articles])

    with open(timestamp_file, "w", encoding="utf-8") as f:
        f.write(last_search_time)


def copy_local_to_crowdin(source_language, target_language):
    repository = get_repository(learn_domain)

    outdated_web_content_articles = get_outdated_articles(source_language, 'web_content')
    language_folder = "%s/%s/%s" % (learn_scratch_dir, source_language[:2], 'web_content')

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

    if len(outdated_web_content_articles) == 0:
        return False

    crowdin_upload_sources(
        repository, source_language[:2], target_language[:2], outdated_web_content_articles[:batch_size]
    )

    os.chdir(old_dir)

    return True


def load_web_content_titles(source_language, target_language):
    web_content_titles = {}

    source_folder = "%s/web_content" % source_language[:2]
    target_folder = "%s/web_content" % target_language[:2]

    for html_file_name in [x for x in os.listdir(target_folder) if x[-5:] == ".html"]:
        article_id = html_file_name[:-5]

        json_file = "%s/%s.json" % (source_folder, article_id)
        html_file = "%s/%s" % (target_folder, html_file_name)

        with open(json_file, "r", encoding="utf-8") as f:
            source_data = json.load(f)

        target_title = source_data["title"]
        friendly_url = "/w/%s" % source_data["friendlyUrlPath"]

        with open(html_file, "r", encoding="utf-8") as f:
            target_content = f.read()

        target_document = BeautifulSoup(target_content, features="html.parser")

        h1_element = target_document.find(lambda x: x.name.lower() == "h1")
        if h1_element is not None:
            target_title = h1_element.getText()

        web_content_titles[friendly_url] = target_title

    return web_content_titles


def copy_local_to_learn(source_language, target_language):
    outdated_web_content_articles = get_outdated_articles(target_language, 'web_content')

    old_dir = os.getcwd()
    os.chdir(learn_scratch_dir)

    web_content_titles = load_web_content_titles(source_language, target_language)

    for html_file in outdated_web_content_articles:
        article_id = html_file[html_file.rfind("/") + 1 : -5]
        publish_translated_web_content_article(article_id, source_language, target_language, web_content_titles)

    os.chdir(old_dir)


def get_outdated_articles(language, subfolder):
    language_folder = "%s/%s/%s" % (learn_scratch_dir, language[:2], subfolder)
    outdated_articles = []

    if not os.path.exists(language_folder):
        print(len(outdated_articles), "out of date files")

        return outdated_articles

    for html_file_name in [x for x in os.listdir(language_folder) if x[-5:] == ".html"]:
        if learn_domain.find("localhost") != -1:
            outdated_articles.append(os.path.join(subfolder, html_file_name))
            continue

        html_file = "%s/%s" % (language_folder, html_file_name)
        hash_file = "%s.crc32" % html_file

        if not os.path.exists(hash_file):
            print('missing hash %s' % hash_file)
            outdated_articles.append(os.path.join(subfolder, html_file_name))
            continue

        with open(hash_file, "r", encoding="utf-8") as f:
            old_hash = f.read()

        with open(html_file, "rb") as f:
            new_hash = str(binascii.crc32(f.read()))

        if old_hash != new_hash:
            print('mismatched hash %s' % hash_file)
            outdated_articles.append(os.path.join(subfolder, html_file_name))

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
    headless_headers = authorize()
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


def fix_styles(html_content):
    return html_content.replace("<em>", "<strong>").replace("</em>", "</strong>")


def publish_translated_web_content_article(article_id, source_language, target_language, web_content_titles):
    html_file = "%s/web_content/%s.html" % (target_language[:2], article_id)

    with open(html_file, "r", encoding="utf-8") as f:
        html_content = f.read()

    update_content = fix_styles(html_content)

    if target_language in disclaimer:
        update_content = '<div class="adm-block adm-note">%s</div>%s' % (
            disclaimer[target_language],
            html_content,
        )

    method, params = get_update_params(
        article_id, source_language, target_language, update_content, web_content_titles
    )

    json_file = "%s/web_content/%s.html.json" % (target_language[:2], article_id)

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(params, f)

    if method is None:
        return

    status_code, response_data = make_headless_request(
        f"{learn_url}/o/headless-delivery/v1.0/structured-contents/{article_id}",
        method,
        target_language,
        params,
    )

    if status_code == 200:
        if learn_domain.find("localhost") == -1:
            with open("%s.crc32" % html_file, "w", encoding="utf-8") as f:
                f.write(str(binascii.crc32(html_content.encode("utf-8"))))
    else:
        print(
            "failed to publish %s (status code: %d, data: %s)"
            % (html_file, status_code, json.dumps(response_data))
        )

def get_translated_title(item, web_content_titles):
    if "url" not in item:
        return item

    url = item["url"]
    title = web_content_titles[url] if url in web_content_titles else item["title"]

    return {
        "url": url,
        "title": title,
    }


def get_content_field_data(field, update_content, web_content_titles):
    if field["name"] == "content":
        return update_content
    
    data = field["contentFieldValue"]["data"]

    if data is None or len(data) == 0:
        return data

    if field["name"] == "navigation":
        navigation = json.loads(data)
        return json.dumps({
            "self": get_translated_title(navigation["self"], web_content_titles),
            "parent": get_translated_title(navigation["parent"], web_content_titles),
            "siblings": [get_translated_title(sibling, web_content_titles) for sibling in navigation["siblings"]],
            "children": [get_translated_title(child, web_content_titles) for child in navigation["children"]],
            "breadcrumb": [get_translated_title(crumb, web_content_titles) for crumb in navigation["breadcrumb"]],
        })

    return data


def get_update_params(article_id, source_language, target_language, update_content, web_content_titles):
    status_code, source_data = make_headless_request(
        f"{learn_url}/o/headless-delivery/v1.0/structured-contents/{article_id}",
        "GET",
        source_language,
        {},
    )

    if status_code != 200:
        return None, None

    available_languages = source_data["availableLanguages"]
    friendly_url = "/w/%s" % source_data["friendlyUrlPath"]
    update_title = web_content_titles[friendly_url]

    params = {
        key: value for key, value in source_data.items()
            if key in ["contentStructureId", "friendlyUrlPath", "customFields", "description"]
    }

    params["title"] = update_title

    params["contentFields"] = [
        {
            "name": field["name"],
            "contentFieldValue": {
                "data": get_content_field_data(field, update_content, web_content_titles)
            },
        }
        for field in source_data["contentFields"]
    ]

    if target_language not in available_languages:
        params["availableLanguages"] = available_languages + [target_language]
    else:
        params["availableLanguages"] = available_languages

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

        if "check_outdated_files" in actions:
            get_outdated_articles(source_language, "web_content")

        if "copy_learn_to_local" in actions:
            copy_learn_to_local("en-US")

        if "copy_local_to_crowdin" in actions:
            copy_local_to_crowdin("en-US", "ja-JP")

        if "translate_learn_on_crowdin" in actions:
            translate_learn_on_crowdin("en-US", "ja-JP")

        if "copy_crowdin_to_local" in actions:
            copy_crowdin_to_local("en-US", "ja-JP")

        if "copy_local_to_learn" in actions:
            copy_local_to_learn("en-US", "ja-JP")
    finally:
        save_session()
