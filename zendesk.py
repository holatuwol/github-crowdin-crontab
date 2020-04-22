from collections import defaultdict
from crowdin_sync import update_repository
from datetime import datetime
from file_manager import get_eligible_files
import git
import json
import logging
import math
import os
import pandas as pd
from repository import initial_dir
from scrape_liferay import authenticate, session

def set_default_parameter(parameters, name, default_value):
    if name not in parameters:
        parameters[name] = default_value

def zendesk_json_request(domain, api_path, attribute_name, request_type, json_params):
    auth_headers = {
        'Authorization': 'Bearer %s' % git.config('%s.token' % domain)
    }

    url = 'https://%s/api/v2%s' % (domain, api_path)

    logging.info(url)

    if request_type == 'POST':
        r = session.post(url, headers=auth_headers, json=json_params)
    elif request_type == 'PUT':
        r = session.put(url, headers=auth_headers, json=json_params)
    else:
        return None

    api_result = json.loads(r.text)

    if attribute_name in api_result:
        return api_result[attribute_name]
    else:
        print(r.text)
        return None

# Create a method to make requests against the ZenDesk API, working around a
# bug in the ZenDesk incremental API: normally, API expects you to be able to
# continually use `next_page`. However, if you upload more than 1 page worth
# of entries within 1 second, the `next_page` becomes useless (this can happen
# if we bulk import articles via API, for example).

def zendesk_get_request(domain, api_path, attribute_name, params=None):
    parameters = {}

    if params is not None:
        parameters.update(params)

    result = []

    set_default_parameter(parameters, 'per_page', 100)
    set_default_parameter(parameters, 'sort_by', 'created_at')
    set_default_parameter(parameters, 'page', 1)

    api_result = None
    page_count = None

    incremental = api_path.find('/incremental/') != -1

    while page_count is None or parameters['page'] <= page_count:
        query_string = '&'.join('%s=%s' % (key, value) for key, value in parameters.items())

        if len(query_string) == 0:
            url = 'https://%s/api/v2%s' % (domain, api_path)
        else:
            url = 'https://%s/api/v2%s?%s' % (domain, api_path, query_string)

        if url is None:
            break

        logging.info(url)

        r = session.get(url)

        api_result = json.loads(r.text)

        if attribute_name in api_result:
            if type(api_result[attribute_name]) == list:
                result = result + api_result[attribute_name]
            else:
                result.append(api_result[attribute_name])
        else:
            print(r.text)
            return None

        parameters['page'] = parameters['page'] + 1

        if 'page_count' in api_result:
            page_count = api_result['page_count']
        elif 'count' in api_result:
            page_count = math.ceil(api_result['count'] / parameters['per_page'])
        else:
            page_count = 1

    return result

def init_zendesk(domain):
    logging.info('Authenticating with Liferay SAML IdP')
    authenticate('https://%s/access/login' % domain, None)

    return zendesk_get_request(domain, '/users/me.json', 'user')[0]

def get_zendesk_articles(domain):
    user = init_zendesk(domain)
    logging.info('Authenticated as %s' % user['email'])
    assert(user['verified'])

    # Reload the articles we already know about

    articles = {}

    try:
        with open('%s/articles_%s.json' % (initial_dir, domain), 'r') as f:
            articles = json.load(f)
    except:
        pass

    # Fetch new articles with the incremental API

    new_start_time = 0 if len(articles) == 0 else max([article['updated_at'] for article in articles.values()])

    article_parameters = {
        'start_time': new_start_time
    }

    new_articles = zendesk_get_request(domain, '/help_center/incremental/articles.json', 'articles', article_parameters)

    logging.info('Found %d articles updated since %s' % (len(new_articles), new_start_time))

    # Override past articles

    articles.update({str(article['id']): article for article in new_articles})

    # Cache the articles on disk so we can work on them without having to go back to the API

    with open('%s/articles_%s.json' % (initial_dir, domain), 'w') as f:
        json.dump(articles, f)

    return articles

def update_zendesk_articles(repository, domain):
    articles, refresh_paths = download_zendesk_articles(repository, domain)
    dest_folder = repository.crowdin.dest_folder

    new_files, all_files, file_info = update_repository(repository, refresh_paths)

    os.chdir(repository.github.git_root)

    for file in all_files:
        article_id = file[file.rfind('/')+1:file.find('-', file.rfind('/'))]
        article = articles[article_id]

        if update_zendesk_translation(domain, article, file):
            target_file = 'ja/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/ja/')
            git.add(target_file)

    git.commit('-m', 'Translated new articles: %s' % datetime.now())

    os.chdir(initial_dir)

    return articles

def download_zendesk_articles(repository, domain):
    user = init_zendesk(domain)
    logging.info('Authenticated as %s' % user['email'])
    assert(user['verified'])

    # Determine the proper folder structure

    category_list = zendesk_get_request(domain, '/help_center/en-us/categories.json', 'categories')
    section_list = zendesk_get_request(domain, '/help_center/en-us/sections.json', 'sections')

    category_names = {
        category['id']: category['name'] for category in category_list
    }

    section_paths = {
        section['id']: '%s%s' % (category_names[section['category_id']], section['html_url'][section['html_url'].rfind('/'):])
            for section in section_list
    }

    articles = get_zendesk_articles(domain)

    def get_category_article_path(article):
        section_path = section_paths[article['section_id']]
        date_folder = pd.to_datetime(article['created_at']).strftime('%G_w%V')
        url_name = article['html_url'][article['html_url'].rfind('/'):]

        return 'en/%s/%s%s.html' % (section_path, date_folder, url_name)

    os.chdir(repository.github.git_root)

    old_article_paths = {
        file[file.rfind('/')+1:file.find('-', file.rfind('/'))]: file
             for file in git.ls_files('en/').split('\n')
    }

    new_article_paths = {
        str(article['id']): get_category_article_path(article)
            for article in articles.values()
                if is_tracked_article(article, section_paths)
    }

    for article_id, article_path in new_article_paths.items():
        os.makedirs(os.path.dirname(article_path), exist_ok=True)
        os.makedirs('ja/' + os.path.dirname(article_path)[3:], exist_ok=True)

    for article_id, new_article_path in new_article_paths.items():
        if article_id not in old_article_paths:
            continue

        old_article_path = old_article_paths[article_id]

        if old_article_path == new_article_path:
            continue

        if os.path.exists(old_article_path):
            os.rename(old_article_path, new_article_path)
            git.add(old_article_path)
            git.add(new_article_path)

        old_article_path = 'ja/' + old_article_path[3:]
        new_article_path = 'ja/' + article_path[3:]

        if os.path.exists(old_article_path):
            os.rename(old_article_path, new_article_path)
            git.add(old_article_path)
            git.add(new_article_path)

    git.commit('-m', 'Renamed articles: %s' % datetime.now())

    for article_id, article_path in new_article_paths.items():
        if article_id in articles and articles[article_id]['body'] is not None:
            with open(article_path, 'w', encoding='utf-8') as f:
                f.write('<h1>%s</h1>\n' % articles[str(article_id)]['title'])
                f.write(articles[str(article_id)]['body'])

            git.add(article_path)
        else:
            print('Missing %s with path %s' % (article_id, article_path))

    git.commit('-m', 'Downloaded new articles: %s' % datetime.now())

    refresh_paths = [
        article_path for article_id, article_path in new_article_paths.items()
            if requires_update(articles[article_id])
    ]

    for article_id, article_path in new_article_paths.items():
        target_file = 'ja/' + article_path[3:]

        if os.path.exists(target_file) and os.path.getsize(target_file) > 0:
            continue

        if 'ja' not in articles[article_id]['label_names']:
            continue

        translation = zendesk_get_request(domain, '/help_center/articles/%s/translations/ja.json' % article_id, 'translation')[0]

        with open(target_file, 'w', encoding='utf-8') as f:
            f.write('<h1>%s</h1>\n' % translation['title'])
            f.write(translation['body'])

        git.add(target_file)

    git.commit('-m', 'Downloaded existing translation: %s' % datetime.now())

    section_categories = {
        section['id']: section['category_id']
            for section in section_list
    }

    new_section_ids = set([
        articles[article_id]['section_id'] for article_id in new_article_paths.keys()
    ])

    new_category_ids = set([
        section_categories[section_id] for section_id in new_section_ids
    ])

    new_section_titles = {
        section_id: zendesk_get_request(domain, '/help_center/sections/%s/translations/ja.json' % section_id, 'translation')[0]['title']
            for section_id in new_section_ids
    }

    new_category_titles = {
        category_id: zendesk_get_request(domain, '/help_center/categories/%s/translations/ja.json' % category_id, 'translation')[0]['title']
            for category_id in new_category_ids
    }

    article_metadata = {}

    for article_id, article_path in new_article_paths.items():
        article = articles[article_id]
        title = article['title']

        target_file = 'ja/' + article_path[3:]

        if not os.path.isfile(target_file):
            continue

        with open(target_file, 'r') as f:
            lines = f.readlines()
            title = lines[0][4:-6]
            
        article_metadata[article_id] = {
            'category': new_category_titles[section_categories[article['section_id']]],
            'section': new_section_titles[article['section_id']],
            'title': title,
            'created': article['created_at'],
            'updated': article['updated_at'],
            'outdated': 'ja' in article['outdated_locales'],
            'mt': 'mt' in article['label_names']
        }

    with open('translations.json', 'w') as f:
        json.dump(article_metadata, f, separators=(',', ':'))

    os.chdir(initial_dir)

    return articles, refresh_paths

def is_tracked_article(article, section_paths=None):
    if article['draft']:
        return False

    if article['locale'] != 'en-us':
        return False

    if section_paths is None:
        return True

    section_path = section_paths[article['section_id']]
    category_name = section_path[0:section_path.find('/')]
    label_names = article['label_names']

    if category_name != 'Announcements' and category_name != 'Knowledge Base':
        if 'Knowledge Base' not in label_names and 'Fast Track' not in label_names:
            return False

    return True

def requires_update(article):
    if 'ja' not in article['label_names']:
        return True

    if 'mt' not in article['label_names']:
        return False

    if 'ja' not in article['outdated_locales']:
        return False

    return True

def update_zendesk_translation(domain, article, file):
    if not requires_update(article):
        return False

    target_file = 'ja/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/ja/')

    if not os.path.exists(target_file):
        return False

    api_path = '/help_center/articles/%s/translations/missing.json' % article['id']

    missing_locales = zendesk_get_request(domain, api_path, 'locales')

    disclaimer_text = '''
<p class="alert alert-info"><span class="wysiwyg-color-blue120">
ファストトラック記事は、お客様の利便性のために一部機械翻訳されています。また、ドキュメントは頻繁に更新が加えられており、翻訳は未完成の部分が含まれることをご了承ください。最新情報は都度公開されておりますため、必ず英語版をご参照ください。翻訳に問題がある場合は、<a href="mailto:support-content-jp@liferay.com">こちら</a>までご連絡ください。
</span></p>
'''

    with open(target_file, 'r') as f:
        lines = f.readlines()
        new_title = lines[0][4:-6]
        new_content = disclaimer_text + '\n'.join(lines[1:])

    if 'ja' in missing_locales:
        json_params = {
            'translation': {
                'locale': 'ja',
                'title': new_title,
                'body': new_content
            }
        }

        api_path = '/help_center/articles/%s/translations.json' % article['id']

        zendesk_json_request(domain, api_path, 'translation', 'POST', json_params)
    else:
        json_params = {
            'translation': {
                'title': new_title,
                'body': new_content
            }
        }

        api_path = '/help_center/articles/%s/translations/ja.json' % article['id']

        zendesk_json_request(domain, api_path, 'translation', 'PUT', json_params)

    article['label_names'].append('ja')
    article['label_names'].append('mt')

    json_params = {
        'article': {
            'user_segment_id': article['user_segment_id'],
            'label_names': article['label_names']
        }
    }

    api_path = '/help_center/articles/%s.json' % article['id']

    zendesk_json_request(domain, api_path, 'article', 'PUT', json_params)

    return True