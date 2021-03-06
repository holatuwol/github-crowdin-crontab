from collections import defaultdict
from crowdin_sync import update_repository
from datetime import datetime
from disclaimer import add_disclaimer_zendesk, disclaimer_zendesk
from file_manager import get_eligible_files, get_crowdin_file
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

def get_article_id(file):
    return file[file.rfind('/')+1:file.find('-', file.rfind('/'))]

def zendesk_json_request(domain, api_path, attribute_name, request_type, json_params):
    auth_headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer %s' % git.config('%s.token' % domain)
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

def get_article_path(en_article, language, section_paths):
    section_path = section_paths[str(en_article['section_id'])]
    date_folder = pd.to_datetime(en_article['created_at']).strftime('%G_w%V')
    url_name = en_article['html_url'][en_article['html_url'].rfind('/'):]

    return '%s/%s/%s%s.html' % (language[0:2], section_path, date_folder, url_name)

def get_zendesk_article(domain, article_id, language):
    api_path = '/help_center/%s/articles/%s.json' % (language, article_id)
    mt_articles = zendesk_get_request(domain, api_path, 'article')

    if mt_articles is None:
        return None

    article = mt_articles[0]

    return article

def update_translated_at(domain, article_id, language, article, articles, section_paths):
    en_article = get_zendesk_article(domain, article_id, 'en-us')

    if en_article is None:
        return

    mt_article = get_zendesk_article(domain, article_id, language)

    article['translated_at'] = {
        'en-us': en_article['edited_at']
    }

    if mt_article is not None:
        article['translated_at'][language] = mt_article['edited_at']

def get_new_articles(domain):
    all_articles = {}

    try:
        with open('%s/all_articles_%s.json' % (initial_dir, domain), 'r') as f:
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

    with open('%s/all_articles_%s.json' % (initial_dir, domain), 'w') as f:
        json.dump(all_articles, f)

    return all_articles

def get_zendesk_articles(repository, domain, language):
    user = init_zendesk(domain)
    logging.info('Authenticated as %s' % user['email'])
    assert(user['verified'])

    # Fetch the categories and sections

    categories = get_categories(domain, language)
    sections = get_sections(domain, language)

    section_paths = {
        section_id: '%s%s' % (categories[str(section['category_id'])]['name'], section['html_url'][section['html_url'].rfind('/'):])
            for section_id, section in sorted(sections.items())
    }

    # Reload the articles we already know about

    articles = {}

    try:
        with open('%s/articles_%s.json' % (initial_dir, domain), 'r') as f:
            articles = json.load(f)
    except:
        pass

    # Fetch all articles (let the delegated method handle update tracking)

    all_articles = get_new_articles(domain)
    new_tracked_articles = {}

    # Check for updates by comparing against our last set of tracked articles

    for article_id, article in all_articles.items():
        if article_id in articles:
            if not is_tracked_article(article, section_paths):
                del articles[article_id]
            elif article['updated_at'] != articles[article_id]['updated_at']:
                new_tracked_articles[article_id] = article
        elif is_tracked_article(article, section_paths):
            new_tracked_articles[article_id] = article

    articles.update(new_tracked_articles)

    logging.info('Found %d new/updated tracked articles' % len(new_tracked_articles))

    old_dir = os.getcwd()
    os.chdir(repository.github.git_root)

    for article_id, article in sorted(articles.items()):
        if 'translated_at' not in article or language not in article['translated_at']:
            update_translated_at(domain, article_id, language, article, articles, section_paths)

    for article_id, article in sorted(new_tracked_articles.items()):
        update_translated_at(domain, article_id, language, article, new_tracked_articles, section_paths)

    # Cache the articles on disk so we can work on them without having to go back to the API

    with open('%s/articles_%s.json' % (initial_dir, domain), 'w') as f:
        json.dump(articles, f)

    os.chdir(old_dir)

    return articles, new_tracked_articles, categories, sections, section_paths

def sync_articles(repository, domain, language, articles, article_paths, refresh_articles=None, refresh_paths=None):
    if refresh_articles is not None:
        logging.info('Updating translations for %d articles' % len(refresh_paths))

        new_files, all_files, file_info = update_repository(repository, list(refresh_paths.values()), sync_sources=True)
    else:
        logging.info('Downloading latest translations for %d articles' % len(article_paths))

        new_files, all_files, file_info = update_repository(repository, list(article_paths.values()), sync_sources=False)

    old_dir = os.getcwd()

    os.chdir(repository.github.git_root)

    for article_id, file in sorted(article_paths.items()):
        article = articles[article_id]
        target_file = language + '/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/%s/' % language)

        if not os.path.isfile(target_file):
            continue

        if language in article['label_names'] and 'mt' not in article['label_names']:
            print(target_file, 'not machine translated')
            os.remove(target_file,)
            git.checkout(target_file)
            continue

        crowdin_file = get_crowdin_file(repository, file)

        if crowdin_file not in file_info:
            continue

        file_metadata = file_info[crowdin_file]

        if file_metadata['phrases'] != file_metadata['translated']:
            print(target_file, 'not fully translated')
            os.remove(target_file)
            git.checkout(target_file)
            continue

        new_title, old_content, new_content = add_disclaimer_zendesk(article, target_file, language)

        if old_content != new_content:
            with open(target_file, 'w') as f:
                f.write('<h1>%s</h1>\n' % new_title)
                f.write(new_content)

        git.add(target_file)

    if refresh_articles is not None:
        git.commit('-m', 'Translated new articles: %s' % datetime.now())
    else:
        git.commit('-m', 'Translated existing articles: %s' % datetime.now())

    os.chdir(old_dir)

    return file_info

def copy_crowdin_to_zendesk(repository, domain, language):
    articles, new_tracked_articles, categories, sections, section_paths = get_zendesk_articles(repository, domain, language)

    old_dir = os.getcwd()

    article_paths = check_renamed_articles(repository, language, articles, section_paths)

    file_info = sync_articles(repository, domain, language, articles, {})

    updated_source_files = [
        article_paths[article_id]
            for article_id, article in articles.items()
                if 'crowdin_sync_at' not in article
    ]

    updated_target_files = [
        language + '/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/%s/' % language)
            for file in updated_source_files
    ]

    missing_language_article_ids = [article['id'] for article in articles.values() if language not in article['label_names']]

    logging.info('%d updated files, %d missing %s label' % (len(updated_target_files), len(missing_language_article_ids), language))

    # Identify the articles which were added to the Git index and send them to Zendesk

    os.chdir(repository.github.git_root)

    for article_id, file in sorted(article_paths.items()):
        article = articles[article_id]
        target_file = language + '/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/%s/' % language)

        if language in article['label_names'] and target_file not in updated_target_files:
            continue

        update_zendesk_translation(repository, domain, article, file, language)

    os.chdir(old_dir)

def copy_zendesk_to_crowdin(repository, domain, language):
    articles, article_paths, refresh_articles, refresh_paths = download_zendesk_articles(repository, domain, language)

    sync_articles(repository, domain, language, articles, article_paths, refresh_articles, refresh_paths)

    with open('%s/articles_%s.json' % (initial_dir, domain), 'w') as f:
        json.dump(articles, f)

    return refresh_articles

def check_renamed_articles(repository, language, articles, section_paths):
    old_dir = os.getcwd()
    os.chdir(repository.github.git_root)

    old_article_paths = {
        get_article_id(file): file
             for file in git.ls_files('en/').split('\n')
    }

    new_article_paths = {
        str(article['id']): get_article_path(article, 'en', section_paths)
            for article in articles.values()
                if is_tracked_article(article, section_paths)
    }

    old_translated_paths = {
        get_article_id(file): file
             for file in git.ls_files(language + '/').split('\n')
    }

    new_translated_paths = {
        str(article['id']): get_article_path(article, language, section_paths)
            for article in articles.values()
                if is_tracked_article(article, section_paths)
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

def save_article_metadata(domain, repository, language, articles, article_paths, categories, sections):
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

        target_file = language + '/' + article_path[3:]

        if not os.path.isfile(target_file):
            continue

        with open(target_file, 'r') as f:
            lines = f.readlines()
            title = lines[0][4:-6]

        section = sections[str(article['section_id'])]
        category = categories[str(section['category_id'])]

        article_metadata[article_id] = {
            'category': category['title_' + language],
            'section': section['title_' + language],
            'title': title,
            'mt': 'mt' in article['label_names']
        }

        if 'translated_at' in article:
            article_metadata[article_id]['translated_at'] = article['translated_at']

    with open('translations.json', 'w') as f:
        json.dump(article_metadata, f, separators=(',', ':'))

    os.chdir(old_dir)

def get_categories(domain, language):
    categories = {}

    if os.path.exists('%s/categories_%s.json' % (initial_dir, domain)):
        with open('%s/categories_%s.json' % (initial_dir, domain), 'r') as f:
            categories = json.load(f)

    category_list = zendesk_get_request(domain, '/help_center/en-us/categories.json', 'categories')

    for category in category_list:
        category_id = str(category['id'])

        if category_id in categories and 'title_' + language in categories[category_id]:
            continue

        translations = zendesk_get_request(domain, '/help_center/categories/%s/translations/%s.json' % (category_id, language), 'translation')

        if translations is not None and len(translations) > 0:
            category['title_' + language] = translations[0]['title']

        categories[category_id] = category

    with open('%s/categories_%s.json' % (initial_dir, domain), 'w') as f:
        json.dump(categories, f)

    return categories

def get_sections(domain, language):
    sections = {}

    if os.path.exists('%s/sections_%s.json' % (initial_dir, domain)):
        with open('%s/sections_%s.json' % (initial_dir, domain), 'r') as f:
            sections = json.load(f)

    section_list = zendesk_get_request(domain, '/help_center/en-us/sections.json', 'sections')

    for section in section_list:
        section_id = str(section['id'])

        if section_id in sections and 'title_' + language in sections[section_id]:
            continue

        translations = zendesk_get_request(domain, '/help_center/sections/%s/translations/%s.json' % (section_id, language), 'translation')

        if translations is not None and len(translations) > 0:
            section['title_' + language] = translations[0]['title']

        sections[section_id] = section

    with open('%s/sections_%s.json' % (initial_dir, domain), 'w') as f:
        json.dump(sections, f)

    return sections

def download_zendesk_articles(repository, domain, language):
    user = init_zendesk(domain)
    logging.info('Authenticated as %s' % user['email'])
    assert(user['verified'])

    # Download current article information and rearrange articles that may have
    # moved categories.

    articles, new_tracked_articles, categories, sections, section_paths = get_zendesk_articles(repository, domain, language)
    article_paths = check_renamed_articles(repository, language, articles, section_paths)

    for article_id, article_path in sorted(article_paths.items()):
        if article_id not in articles:
            print('Missing data for %s with path %s' % (article_id, article_path))
            continue

    # Save articles and translations that currently exist on zendesk

    save_article_metadata(domain, repository, language, articles, article_paths, categories, sections)

    old_dir = os.getcwd()
    os.chdir(repository.github.git_root)

    # First pass: check if anything appears to be out of date

    candidate_article_ids = [
        article_id
            for article_id, article in sorted(articles.items())
                if requires_update(repository, domain, article, language, article_paths[article_id])
    ]

    # Second pass: anything that looks outdated, make sure its translation metadata is up-to-date

    for article_id in candidate_article_ids:
        update_translated_at(domain, article_id, language, articles[article_id], articles, section_paths)

    with open('%s/articles_%s.json' % (initial_dir, domain), 'w') as f:
        json.dump(articles, f)

    # Third pass: assume metadata is complete, check what is out of date

    refresh_articles = {
        article_id: articles[article_id]
            for article_id in candidate_article_ids
                if requires_update(repository, domain, articles[article_id], language, article_paths[article_id])
    }

    # Cache the articles on disk so we can work on them without having to go back to the API

    with open('%s/articles_%s.json' % (initial_dir, domain), 'w') as f:
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

with open('%s/zendesk_tracked_categories.txt' % initial_dir, 'r') as f:
    tracked_categories = [line.strip() for line in f.readlines()]

tracked_labels = []

with open('%s/zendesk_tracked_labels.txt' % initial_dir, 'r') as f:
    tracked_labels = [line.strip() for line in f.readlines()]

def is_tracked_article(article, section_paths):
    if article['draft']:
        return False

    if article['locale'] != 'en-us':
        return False

    section_path = section_paths[str(article['section_id'])]
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

    if new_content != content:
        print('replaced nbsp')

    content = new_content
    new_content = new_content.replace('</span><span>', '').replace('</span> <span>', ' ')

    if new_content != content:
        print('replaced empty span')

    return new_content

def requires_update(repository, domain, article, language, file):
    # check if machine translation is needed

    if language not in article['label_names']:
        logging.info('%s (missing %s label)' % (article['id'], language))
        return True

    if 'mt' not in article['label_names']:
        return False

    # check if it's a new file

    if not os.path.isfile(file):
        logging.info('%s (new source file)' % article['id'])
        return True

    # check if we have a date for the last translation

    if language not in article['translated_at']:
        logging.info('%s (missing %s label)' % (article['id'], language))
        return True

    if article['translated_at']['en-us'][0:10] <= article['translated_at'][language][0:10]:
        return False

    # check if a translation is missing

    target_file = language + '/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/%s/' % language)
    target_path = '%s/%s' % (repository.github.git_root, target_file)

    if not os.path.exists(target_path):
        logging.info('%s (no translation %s)' % (article['id'], target_path))
        return True

    # check if the source language was changed

    with open(file, 'r') as f:
        old_content = ''.join(f.readlines()).strip()

    new_content = '<h1>%s</h1>\n%s' % (article['title'], article['body'])

    if old_content != new_content:
        logging.info('%s (%s > %s)' % (article['id'], article['translated_at']['en-us'][0:10], article['translated_at'][language][0:10]))
        return True

    # check if it's missing a disclaimer

    missing_disclaimer = True
    new_title, old_content, new_content = add_disclaimer_zendesk(article, target_file, language)

    if old_content == new_content:
        missing_disclaimer = False
    else:
        mt_article = get_zendesk_article(domain, article['id'], language)

        if mt_article is None:
            logging.info('%s (deleted article)' % article['id'])
            return False

        missing_disclaimer = mt_article['body'].find(disclaimer_zendesk.strip()) == -1

    if missing_disclaimer:
        logging.info('%s (missing MT disclaimer)' % article['id'])
        return True

    logging.info('%s (outdated, but text matches)' % article['id'])
    return False

def update_zendesk_translation(repository, domain, article, file, language):
    target_file = language + '/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/%s/' % language)

    if not os.path.exists(target_file):
        print('%s (skipping translation not available on file system)' % article['id'])
        return False

    if language in article['label_names'] and 'mt' not in article['label_names']:
        print('%s (skipping translation, not supposed to be updated since it was manually translated)' % article['id'])
        return False

    # Update the labels

    update_labels = False

    if language not in article['label_names']:
        article['label_names'].append(language)
        update_labels = True

        if 'mt' not in article['label_names']:
            article['label_names'].append('mt')

    if update_labels:
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

    # Check if the translation needs an update

    new_title, old_content, new_content = add_disclaimer_zendesk(article, target_file, language)

    logging.info('%s (updating translation)' % article['id'])

    # Update the translation

    api_path = '/help_center/articles/%s/translations/missing.json' % article['id']

    try:
        missing_locales = zendesk_get_request(domain, api_path, 'locales')
    except:
        print('Error fetching missing locales for article %s' % article['id'])
        return False

    if missing_locales is None or language in missing_locales:
        json_params = {
            'translation': {
                'locale': language,
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

        api_path = '/help_center/articles/%s/translations/%s.json' % (article['id'], language)

        try:
            zendesk_json_request(domain, api_path, 'translation', 'PUT', json_params)
        except:
            print('Error updating translation for article %s' % article['id'])
            return False

    return True