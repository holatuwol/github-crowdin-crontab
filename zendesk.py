from collections import defaultdict
from crowdin import delete_translation_folder
from crowdin_sync import update_repository
from datetime import datetime
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

def update_zendesk_articles(repositories, domain):
    git_roots = set([repository.github.git_root for repository in repositories])

    for git_root in git_roots:
        articles = download_zendesk_articles(git_root, domain)

    dest_folders = defaultdict(list)

    for repository in repositories:
        dest_folders[repository.crowdin.dest_folder].append(repository)

    for dest_folder, repositories in dest_folders.items():
        for repository in repositories:
            new_files, all_files, file_info = update_repository(repository)

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

def add_category_articles(articles, categories, category_name, sections, article_paths):
    category_id = None

    for category in categories:
        if category['name'] == category_name:
            category_id = category['id']

    if category_id is None:
        return

    section_paths = {
        section['id']: section['html_url'][section['html_url'].rfind('/'):]
            for section in sections
                if section['category_id'] == category_id
    }

    def get_category_article_path(article):
        section_path = section_paths[article['section_id']]
        date_folder = pd.to_datetime(article['created_at']).strftime('%G_w%V')
        url_name = article['html_url'][article['html_url'].rfind('/'):]

        return 'en/%s%s/%s%s.html' % (category_name, section_path, date_folder, url_name)

    article_paths.update({
        str(article['id']): get_category_article_path(article)
            for article in articles.values()
                if article['section_id'] in section_paths and
                    not article['draft'] and
                    article['locale'] == 'en-us' and
                    'Fast Track' not in article['label_names']
    })

def add_label_articles(articles, label_name, article_paths):
    section_path = label_name

    def get_fast_track_article_path(article):
        date_folder = pd.to_datetime(article['created_at']).strftime('%G_w%V')
        url_name = article['html_url'][article['html_url'].rfind('/'):]

        return 'en/%s/%s%s.html' % (section_path, date_folder, url_name)

    article_paths.update({
        str(article['id']): get_fast_track_article_path(article)
            for article in articles.values()
                if not article['draft'] and
                    article['locale'] == 'en-us' and
                    label_name in article['label_names']
    })

def download_zendesk_articles(git_root, domain):
    user = init_zendesk(domain)
    logging.info('Authenticated as %s' % user['email'])
    assert(user['verified'])

    # Determine the proper folder structure

    categories = zendesk_get_request(domain, '/help_center/en-us/categories.json', 'categories')
    sections = zendesk_get_request(domain, '/help_center/en-us/sections.json', 'sections')

    articles = get_zendesk_articles(domain)
    article_paths = {}

    add_category_articles(articles, categories, 'Announcements', sections, article_paths)
    add_category_articles(articles, categories, 'Liferay DXP 7.1 Admin Guide', sections, article_paths)

    add_label_articles(articles, 'Knowledge Base', article_paths)
    add_label_articles(articles, 'Fast Track', article_paths)

    os.chdir(git_root)

    for article_id, article_path in article_paths.items():
        article_file_name = article_path
        article_folder = os.path.dirname(article_file_name)

        if not os.path.exists(article_folder):
            os.makedirs(article_folder)

        if article_id in articles and articles[article_id]['body'] is not None:
            with open(article_file_name, 'w', encoding='utf-8') as f:
                f.write('<h1>%s</h1>\n' % articles[str(article_id)]['title'])
                f.write(articles[str(article_id)]['body'])

            git.add(article_file_name)
        else:
            print('Missing %s with path %s' % (article_id, article_path))

    git.commit('-m', 'Downloaded new articles: %s' % datetime.now())

    os.chdir(initial_dir)

    return articles

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