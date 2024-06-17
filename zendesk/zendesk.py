from bs4 import BeautifulSoup
from collections import defaultdict
from datetime import datetime
import dateutil.parser
import inspect
import json
import logging
import math
from onepassword import OnePassword
import os
import pandas as pd
import sys

script_folder = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
sys.path.insert(0, os.path.dirname(script_folder))

from crowdin import crowdin_download_translations, crowdin_upload_sources, pre_translate
from crowdin_sync import get_repository_state, update_repository
from disclaimer import add_disclaimer_zendesk, disclaimer_zendesk, disclaimer_zendesk_text
from file_manager import get_crowdin_file, get_eligible_files, get_translation_path
import git
from repository import initial_dir

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(script_folder)), 'liferay-faster-deploy/patcher'))

from scrape_liferay import authenticate, session

def set_default_parameter(parameters, name, default_value):
    if name not in parameters:
        parameters[name] = default_value

def get_article_id(file):
    return file[file.rfind('/')+1:file.find('-', file.rfind('/'))]

bearer_configs = {
	domain: git.config('1password.%s' % domain)
		for domain in ['liferay-support.zendesk.com', 'liferaysupport1528999723.zendesk.com']
}

bearer_tokens = {
	domain: OnePassword.get_item(uuid="'%s'" % config, fields='credential')['credential']
		for domain, config in bearer_configs.items() if config is not None and config != ''
}

def zendesk_json_request(domain, api_path, attribute_name, request_type, json_params):
    auth_headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer %s' % bearer_tokens[domain]
    }

    url = 'https://%s/api/v2%s' % (domain, api_path)

    logging.info(url)

    if request_type == 'POST':
        r = session.post(url, headers=auth_headers, json=json_params)
    elif request_type == 'PUT':
        r = session.put(url, headers=auth_headers, json=json_params)
    elif request_type == 'GET' and json_params is None:
        r = session.get(url, headers=auth_headers)
    else:
        return None

    try:
        api_result = json.loads(r.text)
    except:
        print('%d, %s' % (r.status_code, r.text))
        return None

    if attribute_name in api_result:
        return api_result[attribute_name]

    if 'error' in api_result and api_result['error'] == 'RecordNotFound':
        return None

    print('%d, %s' % (r.status_code, r.text))
    exit()

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

        try:
            api_result = json.loads(r.text)
        except:
            print(r.text)
            return None

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
    logging.info('Authenticating with %s Liferay SAML IdP' % domain)
    authenticate('https://%s/access/login?redirect_to=' % domain, None)

    return zendesk_get_request(domain, '/users/me.json', 'user')[0]

def get_article_path(source_article, target_language, section_paths):
    section_path = section_paths[str(source_article['section_id'])]
    url_name = source_article['html_url'][source_article['html_url'].rfind('/'):][:250]

    return '%s/%s%s.html' % (target_language[0:2], section_path, url_name)

def get_zendesk_article(domain, article_id, target_language):
    api_path = '/help_center/articles/%s/translations/%s.json' % (article_id, target_language)
    mt_articles = zendesk_get_request(domain, api_path, 'translation')

    if mt_articles is None:
        return None

    article = mt_articles[0]

    return article

def get_new_articles(domain):
    all_articles = {}

    try:
        with open('%s/zendesk/all_articles_%s.json' % (initial_dir, domain), 'r') as f:
            all_articles = json.load(f)
    except:
        pass

    new_start_time = 0 if len(all_articles) == 0 else max([article['updated_at'] for article in all_articles.values()])

    article_parameters = {
        'start_time': new_start_time
    }

    new_article_list = zendesk_get_request(domain, '/help_center/incremental/articles.json', 'articles', article_parameters)

    new_articles = {
        str(article['id']): article for article in new_article_list
    }

    all_articles.update(new_articles)

    with open('%s/zendesk/all_articles_%s.json' % (initial_dir, domain), 'w') as f:
        json.dump(all_articles, f)

    return all_articles

def get_zendesk_articles(repository, domain, source_language, target_language, fetch_update):
    user = init_zendesk(domain)
    logging.info('Authenticated as %s' % user['email'])
    assert(user['verified'])

    # Fetch the categories and sections

    categories = get_categories(domain, target_language)
    sections = get_sections(domain, target_language)

    section_paths = {
        section_id: '%s%s' % (categories[str(section['category_id'])]['name'], section['html_url'][section['html_url'].rfind('/'):])
            for section_id, section in sorted(sections.items())
    }

    # Reload the articles we already know about

    articles = {}

    try:
        with open('%s/zendesk/articles_%s_%s.json' % (initial_dir, source_language, domain), 'r') as f:
            articles = json.load(f)
    except:
        pass

    # Fetch all articles (let the delegated method handle update tracking)

    new_tracked_articles = {}

    if fetch_update:
        all_articles = get_new_articles(domain)
    else:
        with open('%s/zendesk/all_articles_%s.json' % (initial_dir, domain), 'r') as f:
            all_articles = json.load(f)

    # Check for updates by comparing against our last set of tracked articles

    for article_id, article in all_articles.items():
        if article_id in articles:
            if not is_tracked_article(article, source_language, section_paths):
                del articles[article_id]
            elif article['updated_at'] != articles[article_id]['updated_at']:
                new_tracked_articles[article_id] = article
        elif is_tracked_article(article, source_language, section_paths):
            new_tracked_articles[article_id] = article

    articles.update(new_tracked_articles)

    logging.info('Found %d new/updated tracked articles' % len(new_tracked_articles))

    old_dir = os.getcwd()
    os.chdir(repository.github.git_root)

    # Cache the articles on disk so we can work on them without having to go back to the API

    with open('%s/zendesk/articles_%s_%s.json' % (initial_dir, source_language, domain), 'w') as f:
        json.dump(articles, f)

    os.chdir(old_dir)

    return articles, new_tracked_articles, categories, sections, section_paths

def copy_crowdin_to_zendesk(repository, domain, source_language, target_language, authors=None):
    articles, new_tracked_articles, categories, sections, section_paths = get_zendesk_articles(repository, domain, source_language, target_language, True)

    old_dir = os.getcwd()

    article_paths = check_renamed_articles(repository, source_language, target_language, articles, section_paths)

    if os.path.exists('check_only_articles.txt'):
        with open('check_only_articles.txt', 'r') as f:
            updated_source_files = [
                article_paths[line.strip()]
                    for line in f.readlines()
            ]
    else:
        updated_source_files = [
            article_paths[article_id]
                for article_id, article in articles.items()
        ]

    updated_target_files = [
        get_translation_path(source_file, source_language, target_language)
            for source_file in updated_source_files
    ]

    missing_target_language_article_ids = [article['id'] for article in articles.values() if target_language not in article['label_names']]

    logging.info('%d updated files, %d missing %s label' % (len(updated_target_files), len(missing_target_language_article_ids), target_language))

    # Identify the articles which were added to the Git index and send them to Zendesk

    os.chdir(repository.github.git_root)

    for article_id, source_file in sorted(article_paths.items()):
        article = articles[article_id]
        target_file = get_translation_path(source_file, source_language, target_language)

        if target_language in article['label_names'] and target_file not in updated_target_files:
            continue

        if authors is None or str(article['author_id']) in authors:
            if authors is not None:
                logging.info('%s (updating since author is included)' % article_id)

            update_zendesk_translation(repository, domain, article, source_file, target_file, source_language, target_language)
        else:
            logging.info('%s (skipping since author is excluded)' % article_id)

    os.chdir(old_dir)

def translate_zendesk_on_crowdin(repository, domain, source_language, target_language):
    new_files, all_files, file_info = get_repository_state(repository, source_language, target_language)

    pre_translate(repository, source_language, target_language, all_files, file_info)

    crowdin_download_translations(repository, source_language, target_language, all_files, file_info)

    old_dir = os.getcwd()

    os.chdir(repository.github.git_root)

    git.add('*.html')
    git.commit('-m', 'Translated existing articles: %s' % datetime.now())

    os.chdir(old_dir)

def copy_zendesk_to_crowdin(repository, domain, source_language, target_language):
    articles, article_paths, refresh_articles, refresh_paths = download_zendesk_articles(repository, domain, source_language, target_language, False)

    with open('%s/zendesk/articles_%s_%s.json' % (initial_dir, source_language, domain), 'w') as f:
        json.dump(articles, f)

    old_dir = os.getcwd()
    os.chdir(repository.github.git_root)

    if len(refresh_paths) > 0:
        print('Uploading %d files to crowdin...' % len(refresh_paths))
        crowdin_upload_sources(repository, source_language, target_language, refresh_paths.values())
    else:
        print('No files have been updated, nothing to upload to crowdin')

    os.chdir(old_dir)

    return refresh_articles

def check_renamed_articles(repository, source_language, target_language, articles, section_paths):
    old_dir = os.getcwd()
    os.chdir(repository.github.git_root)

    source_language_path = source_language

    if source_language.find('-') != -1:
        source_language_path = source_language[:source_language.find('-')]

    target_language_path = target_language

    if target_language.find('-') != -1:
        target_language_path = target_language[:target_language.find('-')]

    old_article_paths = {
        get_article_id(source_file): source_file
             for source_file in git.ls_files(source_language_path + '/').split('\n')
    }

    new_article_paths = {
        str(article['id']): get_article_path(article, source_language_path, section_paths)
            for article in articles.values()
                if is_tracked_article(article, source_language, section_paths)
    }

    old_translated_paths = {
        get_article_id(target_file): target_file
             for target_file in git.ls_files(target_language_path + '/').split('\n')
    }

    new_translated_paths = {
        str(article['id']): get_article_path(article, target_language_path, section_paths)
            for article in articles.values()
                if is_tracked_article(article, source_language, section_paths)
    }

    for article_id, new_article_path in sorted(new_article_paths.items()):
        if article_id not in old_article_paths:
            continue

        old_article_path = old_article_paths[article_id]

        if old_article_path == new_article_path:
            continue

        if not os.path.exists(old_article_path):
            continue

        os.makedirs(os.path.dirname(new_article_path), exist_ok=True)
        os.rename(old_article_path, new_article_path)

        git.add(old_article_path)

        git.add(new_article_path)

    for article_id, new_article_path in sorted(new_translated_paths.items()):
        if article_id not in old_translated_paths:
            continue

        old_article_path = old_translated_paths[article_id]

        if old_article_path == new_article_path:
            continue

        if not os.path.exists(old_article_path):
            continue

        os.makedirs(os.path.dirname(new_article_path), exist_ok=True)
        os.rename(old_article_path, new_article_path)

        git.add(old_article_path)
        git.add(new_article_path)

    git.commit('-m', 'Renamed articles: %s' % datetime.now())

    os.chdir(old_dir)

    return new_article_paths

def save_article_metadata(domain, repository, target_language, articles, article_paths, categories, sections):
    target_language_path = target_language

    if target_language.find('-') != -1:
        target_language_path = target_language[:target_language.find('-')]

    old_dir = os.getcwd()
    os.chdir(repository.github.git_root)

    new_section_ids = set([
        str(articles[article_id]['section_id']) for article_id in articles.keys()
    ])

    new_category_ids = set([
        str(sections[section_id]['category_id']) for section_id in new_section_ids
    ])

    article_metadata = {}

    for article_id, article_path in sorted(article_paths.items()):
        article = articles[article_id]
        title = article['title']

        target_file = target_language_path + '/' + article_path[3:]

        if not os.path.isfile(target_file):
            continue

        with open(target_file, 'r') as f:
            lines = f.readlines()
            title = lines[0][4:-6]

        section = sections[str(article['section_id'])]
        category = categories[str(section['category_id'])]

        article_metadata[article_id] = {
            'category': category['title_' + target_language],
            'section': section['title_' + target_language],
            'title': title,
            'mt': 'mt' in article['label_names']
        }

    with open('translations.json', 'w') as f:
        json.dump(article_metadata, f, separators=(',', ':'))

    os.chdir(old_dir)

def get_categories(domain, target_language):
    categories = {}

    if os.path.exists('%s/zendesk/categories_%s.json' % (initial_dir, domain)):
        with open('%s/zendesk/categories_%s.json' % (initial_dir, domain), 'r') as f:
            categories = json.load(f)

    category_list = zendesk_get_request(domain, '/help_center/en-us/categories.json', 'categories')

    for category in category_list:
        category_id = str(category['id'])

        if category_id in categories and 'title_' + target_language in categories[category_id]:
            continue

        translations = zendesk_get_request(domain, '/help_center/categories/%s/translations/%s.json' % (category_id, target_language), 'translation')

        if translations is not None and len(translations) > 0:
            category['title_' + target_language] = translations[0]['title']

        categories[category_id] = category

    with open('%s/zendesk/categories_%s.json' % (initial_dir, domain), 'w') as f:
        json.dump(categories, f)

    return categories

def get_sections(domain, target_language):
    sections = {}

    if os.path.exists('%s/zendesk/sections_%s.json' % (initial_dir, domain)):
        with open('%s/zendesk/sections_%s.json' % (initial_dir, domain), 'r') as f:
            sections = json.load(f)

    section_list = zendesk_get_request(domain, '/help_center/en-us/sections.json', 'sections')

    for section in section_list:
        section_id = str(section['id'])

        if section_id in sections and 'title_' + target_language in sections[section_id]:
            continue

        translations = zendesk_get_request(domain, '/help_center/sections/%s/translations/%s.json' % (section_id, target_language), 'translation')

        if translations is not None and len(translations) > 0:
            section['title_' + target_language] = translations[0]['title']

        sections[section_id] = section

    with open('%s/zendesk/sections_%s.json' % (initial_dir, domain), 'w') as f:
        json.dump(sections, f)

    return sections

def download_zendesk_articles(repository, domain, source_language, target_language, fetch_update=False):
    user = init_zendesk(domain)
    logging.info('Authenticated as %s' % user['email'])
    assert(user['verified'])

    # Download current article information and rearrange articles that may have
    # moved categories.

    articles, new_tracked_articles, categories, sections, section_paths = get_zendesk_articles(repository, domain, source_language, target_language, fetch_update)
    article_paths = check_renamed_articles(repository, source_language, target_language, articles, section_paths)

    for article_id, article_path in sorted(article_paths.items()):
        if article_id not in articles:
            print('Missing data for %s with path %s' % (article_id, article_path))
            continue

    # Save articles and translations that currently exist on zendesk

    save_article_metadata(domain, repository, target_language, articles, article_paths, categories, sections)

    old_dir = os.getcwd()
    os.chdir(repository.github.git_root)

    # Check if anything appears to be out of date

    if os.path.exists(os.path.join(old_dir, 'check_only_articles.txt')):
        with open(os.path.join(old_dir, 'check_only_articles.txt'), 'r') as f:
            refresh_articles = {
                line.strip(): articles[line.strip()]
                    for line in f.readlines()
            }
    else:
        refresh_articles = {
            article_id: article
                for article_id, article in sorted(articles.items())
                    if requires_update(repository, domain, article, source_language, target_language, article_paths[article_id], None, fetch_update)
        }

    # Cache the articles on disk so we can work on them without having to go back to the API

    with open('%s/zendesk/articles_%s_%s.json' % (initial_dir, source_language, domain), 'w') as f:
        json.dump(articles, f)

    refresh_paths = {
        article_id: article_paths[article_id]
            for article_id in refresh_articles.keys()
    }

    for article_id, article in refresh_articles.items():
        article_path = refresh_paths[article_id]

        os.makedirs(os.path.dirname(article_path), exist_ok=True)

        with open(article_path, 'w', encoding='utf-8') as f:
            f.write('<h1>%s</h1>\n' % article['title'])
            f.write(remove_nbsp(article['body']))

        git.add(article_path)

    git.commit('-m', 'Recently added articles: %s' % datetime.now())

    os.chdir(old_dir)

    return articles, article_paths, refresh_articles, refresh_paths

tracked_categories = []
tracked_labels = []

with open('%s/zendesk/zendesk_tracked_categories.txt' % initial_dir, 'r') as f:
    tracked_categories = [line.strip() for line in f.readlines()]

with open('%s/zendesk/zendesk_tracked_labels.txt' % initial_dir, 'r') as f:
    tracked_labels = [line.strip() for line in f.readlines()]

def is_tracked_article(article, source_language, section_paths):
    if article['draft']:
        return False

    if article['locale'] != source_language:
        return False

    section_id = str(article['section_id'])

    if section_id not in section_paths:
        return False

    section_path = section_paths[section_id]
    category_name = section_path[0:section_path.find('/')]
    label_names = article['label_names']

    if 'mt' in label_names:
        return True

    if category_name in tracked_categories:
        return True

    for label_name in label_names:
        if label_name in tracked_labels:
            return True

    return False

def remove_nbsp(content):
    new_content = content.replace('\xa0', ' ')

    content = new_content
    new_content = new_content.replace('</span><span>', '').replace('</span> <span>', ' ')

    return new_content

def requires_update(repository, domain, article, source_language, target_language, source_file, target_file, fetch_update):
    # check if machine translation is needed

    if target_language not in article['label_names']:
        logging.info('%s (requires update check: missing %s label)' % (article['id'], target_language))
        return True

    if 'mt' not in article['label_names']:
        logging.info('%s (requires update check: manually translated)' % article['id'])
        return False

    # check if it's a new file

    if not os.path.isfile(source_file):
        logging.info('%s (requires update check: new source file)' % article['id'])
        return True

    # check if a translation is missing

    if target_file is None:
        target_file = get_translation_path(source_file, source_language, target_language)

    target_path = '%s/%s' % (repository.github.git_root, target_file)

    if not os.path.exists(target_path):
        logging.info('%s (requires update check: no translation on file system %s)' % (article['id'], target_path))
        return True

    # check if the source target_language was changed

    with open(source_file, 'r') as f:
        old_content = ''.join(f.readlines()).strip()

    new_content = '<h1>%s</h1>\n%s' % (article['title'], remove_nbsp(article['body']))

    if old_content != new_content:
        logging.info('%s (requires update check: mismatched content)' % article['id'])
        return True

    # check if it's missing a disclaimer

    missing_disclaimer = False
    new_title, old_content, new_content = add_disclaimer_zendesk(article, target_file, target_language)

    if fetch_update:
        if get_zendesk_article(domain, article['id'], source_language) is None:
            logging.info('%s (requires update check: deleted article)' % article['id'])
            return False

        mt_article = get_zendesk_article(domain, article['id'], target_language)

        if mt_article is None:
            logging.info('%s (requires update check: missing %s translation on zendesk)' % (article['id'], target_language))
            return True

        mt_article_text = BeautifulSoup(mt_article['body'], features='html.parser').get_text().strip()

        if mt_article_text.find(disclaimer_zendesk_text[target_language]) == -1:
            logging.info('%s (requires update check: missing MT disclaimer)' % article['id'])
            return True

    logging.info('%s (requires update check: no update required)' % article['id'])
    return False

def update_zendesk_translation(repository, domain, article, source_file, target_file, source_language, target_language):
    if not os.path.exists(target_file):
        print('%s (skipping translation, not available on file system %s)' % (article['id'], target_file))
        return False

    if target_language in article['label_names'] and 'mt' not in article['label_names']:
        print('%s (skipping translation, not supposed to be updated since it was manually translated)' % article['id'])
        return False

    # Update the labels

    update_labels = False

    if target_language not in article['label_names']:
        article['label_names'].append(target_language)
        update_labels = True

        if 'mt' not in article['label_names']:
            article['label_names'].append('mt')

    if update_labels:
        logging.info('%s (updating labels)' % article['id'])

        json_params = {
            'article': {
                'user_segment_id': article['user_segment_id'],
                'label_names': article['label_names']
            }
        }

        api_path = '/help_center/articles/%s.json' % article['id']

        try:
            zendesk_json_request(domain, api_path, 'article', 'PUT', json_params)
        except:
            print('Error updating labels for article %s' % article['id'])
            return False

    if 'mt' not in article['label_names']:
        return False

    # Check if the translation needs an update

    if not requires_update(repository, domain, article, source_language, target_language, source_file, target_file, True):
        logging.info('%s (skipping translation, file is up to date %s)' % (article['id'], target_file))
        return False

    new_title, old_content, new_content = add_disclaimer_zendesk(article, target_file, target_language)

    logging.info('%s (updating translation)' % article['id'])

    # Update the translation

    api_path = '/help_center/articles/%s/translations/missing.json' % article['id']

    try:
        missing_locales = zendesk_get_request(domain, api_path, 'locales')
    except:
        print('Error fetching missing locales for article %s' % article['id'])
        return False

    if missing_locales is None or target_language in missing_locales:
        json_params = {
            'translation': {
                'locale': target_language,
                'title': new_title,
                'body': new_content
            }
        }

        api_path = '/help_center/articles/%s/translations.json' % article['id']

        try:
            zendesk_json_request(domain, api_path, 'translation', 'POST', json_params)
        except:
            print('Error adding new translation for article %s' % article['id'])
            return False
    else:
        json_params = {
            'translation': {
                'title': new_title,
                'body': new_content
            }
        }

        api_path = '/help_center/articles/%s/translations/%s.json' % (article['id'], target_language)

        try:
            zendesk_json_request(domain, api_path, 'translation', 'PUT', json_params)
        except:
            print('Error updating translation for article %s' % article['id'])
            return False

    return True
