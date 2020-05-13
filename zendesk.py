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

disclaimer_text = '''
<aside class="alert alert-info"><span class="wysiwyg-color-blue120">
ご覧のページは、お客様の利便性のために一部機械翻訳されています。また、ドキュメントは頻繁に更新が加えられており、翻訳は未完成の部分が含まれることをご了承ください。最新情報は都度公開されておりますため、必ず英語版をご参照ください。翻訳に問題がある場合は、<a href="mailto:support-content-jp@liferay.com">こちら</a>までご連絡ください。
</span></aside>
'''

def set_default_parameter(parameters, name, default_value):
    if name not in parameters:
        parameters[name] = default_value

def get_article_id(file):
    return file[file.rfind('/')+1:file.find('-', file.rfind('/'))]

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

def get_article_path(en_article, language, section_paths):
    section_path = section_paths[str(en_article['section_id'])]
    date_folder = pd.to_datetime(en_article['created_at']).strftime('%G_w%V')
    url_name = en_article['html_url'][en_article['html_url'].rfind('/'):]

    return '%s/%s/%s%s.html' % (language[0:2], section_path, date_folder, url_name)

def get_zendesk_article(domain, article_id, language, articles, section_paths):
    api_path = '/help_center/%s/articles/%s.json' % (language, article_id)
    mt_articles = zendesk_get_request(domain, api_path, 'article')

    if mt_articles is None:
        return None

    article = mt_articles[0]

    if language != 'en-us' and language not in article['label_names']:
        return article

    article_path = get_article_path(articles[article_id], language, section_paths)

    os.makedirs(os.path.dirname(article_path), exist_ok=True)

    with open(article_path, 'w', encoding='utf-8') as f:
        f.write('<h1>%s</h1>\n' % article['title'])
        f.write(article['body'])

    git.add(article_path)

    return article

def update_translated_at(domain, article_id, language, article, articles, section_paths):
    en_article = get_zendesk_article(domain, article_id, 'en-us', articles, section_paths)
    mt_article = get_zendesk_article(domain, article_id, language, articles, section_paths)

    article['translated_at'] = {
        'en-us': en_article['edited_at']
    }

    if mt_article is not None:
        article['translated_at'][language] = mt_article['edited_at']

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

    remove_article_ids = [
        article_id for article_id, article in sorted(articles.items())
            if not is_tracked_article(article, section_paths)
    ]

    for article_id in remove_article_ids:
        if article_id in articles:
            del articles[article_id]

    # Fetch new articles with the incremental API

    new_start_time = 0 if len(articles) == 0 else max([article['updated_at'] for article in articles.values()])

    article_parameters = {
        'start_time': new_start_time
    }

    new_article_list = zendesk_get_request(domain, '/help_center/incremental/articles.json', 'articles', article_parameters)

    new_articles = {
        str(article['id']): article for article in new_article_list
            if is_tracked_article(article, section_paths)
    }

    remove_article_ids = [
        article_id for article_id, article in sorted(new_articles.items())
            if article_id in articles and article['updated_at'] == articles[article_id]['updated_at']
    ]

    for article_id in remove_article_ids:
        del new_articles[article_id]

    # Override past articles

    remove_article_ids = [
        str(article['id']) for article in new_articles.values()
            if not is_tracked_article(article, section_paths)
    ]

    for article_id in remove_article_ids:
        if article_id in articles:
            del articles[article_id]

    articles.update(new_articles)

    new_tracked_articles = {
        article_id: article
            for article_id, article in sorted(new_articles.items())
                if is_tracked_article(article, section_paths)
    }

    logging.info('Found %d tracked articles updated since %s' % (len(new_tracked_articles), new_start_time))

    os.chdir(repository.github.git_root)

    for article_id, article in sorted(articles.items()):
        if 'translated_at' not in article or language not in article['translated_at']:
            update_translated_at(domain, article_id, language, article, articles, section_paths)

    for article_id, article in sorted(new_tracked_articles.items()):
        update_translated_at(domain, article_id, language, article, new_tracked_articles, section_paths)

    # Cache the articles on disk so we can work on them without having to go back to the API

    with open('%s/articles_%s.json' % (initial_dir, domain), 'w') as f:
        json.dump(articles, f)

    git.commit('-m', 'Downloaded updated articles: %s' % datetime.now())

    os.chdir(initial_dir)

    return articles, new_tracked_articles, categories, sections, section_paths

def translate_articles(repository, domain, language, refresh_articles, refresh_paths):
    logging.info('Updating translations for %d articles' % len(refresh_paths))

    update_repository(repository, refresh_paths.values())

    os.chdir(repository.github.git_root)

    for article_id, article in sorted(refresh_articles.items()):
        file = refresh_paths[article_id]

        if update_zendesk_translation(domain, article, file, language):
            target_file = language + '/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/%s/' % language)
            git.add(target_file)

    git.commit('-m', 'Translated new articles: %s' % datetime.now())

    os.chdir(initial_dir)

def update_zendesk_articles(repository, domain, language):
    last_refresh_count = 0
    refresh_articles, refresh_paths = download_zendesk_articles(repository, domain, language)
    dest_folder = repository.crowdin.dest_folder

    while len(refresh_paths) > 0 and last_refresh_count != len(refresh_paths):
        last_refresh_count = len(refresh_paths)
        translate_articles(repository, domain, language, refresh_articles, refresh_paths)
        refresh_articles, refresh_paths = download_zendesk_articles(repository, domain, language)

    return refresh_articles

def check_renamed_articles(repository, language, articles, section_paths):
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

    for article_id, new_article_path in sorted(new_article_paths.items()):
        if article_id not in old_article_paths:
            continue

        old_article_path = old_article_paths[article_id]

        if old_article_path == new_article_path:
            continue

        if os.path.exists(old_article_path):
            os.rename(old_article_path, new_article_path)
            git.add(old_article_path)
            git.add(new_article_path)

        old_article_path = language + '/' + old_article_path[3:]
        new_article_path = language + '/' + new_article_path[3:]

        if os.path.exists(old_article_path):
            os.rename(old_article_path, new_article_path)
            git.add(old_article_path)
            git.add(new_article_path)

    git.commit('-m', 'Renamed articles: %s' % datetime.now())

    os.chdir(initial_dir)

    return new_article_paths

def save_article_metadata(domain, repository, language, articles, article_paths, categories, sections):
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
            'translated_at': article['translated_at'],
            'mt': 'mt' in article['label_names']
        }

    with open('translations.json', 'w') as f:
        json.dump(article_metadata, f, separators=(',', ':'))

    os.chdir(initial_dir)

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

    refresh_articles = {
        article_id: article
            for article_id, article in sorted(articles.items())
                if requires_update(article, language)
    }

    refresh_paths = {
        article_id: article_paths[article_id]
            for article_id in refresh_articles.keys()
    }

    return refresh_articles, refresh_paths

def is_tracked_article(article, section_paths):
    if article['draft']:
        return False

    if article['locale'] != 'en-us':
        return False

    section_path = section_paths[str(article['section_id'])]
    category_name = section_path[0:section_path.find('/')]
    label_names = article['label_names']

    if category_name != 'Announcements' and category_name != 'Knowledge Base':
        if 'Knowledge Base' not in label_names and 'Fast Track' not in label_names:
            return False

    return True

def requires_update(article, language, force=False):
    if language not in article['label_names']:
        logging.info('%s (missing %s label in %s)' % (article['id'], language, ','.join(article['label_names'])))
        return True

    if 'mt' not in article['label_names']:
        return False

    if force:
        logging.info('%s (force update)' % article['id'])
        return True

    if language not in article['translated_at']:
        logging.info('%s (missing %s metadata in %s)' % (article['id'], language, ','.join(article['translated_at'])))
        return True

    if article['translated_at']['en-us'][0:10] > article['translated_at'][language][0:10]:
        logging.info('%s (%s > %s)' % (article['id'], article['translated_at']['en-us'][0:10], article['translated_at'][language][0:10]))
        return True

    return False

def add_disclaimer(article, target_file):
    with open(target_file, 'r') as f:
        lines = f.readlines()

    new_title = lines[0][4:-6]
    old_content = ''.join(lines[1:]).strip()

    if lines[1].strip() == '<p class="alert alert-info"><span class="wysiwyg-color-blue120">':
        new_content = ''.join(lines[4:]).strip()
    if lines[1].strip() == '<aside class="alert alert-info"><span class="wysiwyg-color-blue120">':
        new_content = ''.join(lines[4:]).strip()
    elif len(lines) > 2 and lines[2].strip() == '<p class="alert alert-info"><span class="wysiwyg-color-blue120">':
        new_content = ''.join(lines[5:]).strip()
    elif len(lines) > 2 and lines[2].strip() == '<aside class="alert alert-info"><span class="wysiwyg-color-blue120">':
        new_content = ''.join(lines[5:]).strip()
    else:
        new_content = ''.join(lines[1:]).strip()

    script_disclaimer = new_content.find('var disclaimerElement')

    if script_disclaimer != -1:
        script_disclaimer = new_content.rfind('<script>', 0, script_disclaimer)
        new_content = new_content[0:script_disclaimer].strip()

    if 'mt' in article['label_names']:
        new_content = (disclaimer_text + new_content).strip()

    return new_title, old_content, new_content

def update_zendesk_translation(domain, article, file, language, force=False):
    global disclaimer_text

    if not requires_update(article, language, force):
        return False

    target_file = language + '/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/%s/' % language)

    if not os.path.exists(target_file):
        return False

    # Update the labels

    update_labels = False

    if not force:
        if language not in article['label_names']:
            article['label_names'].append(language)
            update_labels = True

        if 'mt' not in article['label_names']:
            article['label_names'].append('mt')
            update_labels = True

    if update_labels:
        json_params = {
            'article': {
                'user_segment_id': article['user_segment_id'],
                'label_names': article['label_names']
            }
        }

        api_path = '/help_center/articles/%s.json' % article['id']

        zendesk_json_request(domain, api_path, 'article', 'PUT', json_params)

    # Check if the translation needs an update

    new_title, old_content, new_content = add_disclaimer(article, target_file)

    if old_content == new_content:
        return False

    with open(target_file, 'w') as f:
        f.write('<h1>%s</h1>\n' % new_title)
        f.write(new_content)

    git.add(target_file)

    # Update the translation

    api_path = '/help_center/articles/%s/translations/missing.json' % article['id']

    try:
        missing_locales = zendesk_get_request(domain, api_path, 'locales')
    except:
        return False

    if missing_locales is None:
        return False

    if language in missing_locales:
        json_params = {
            'translation': {
                'locale': language,
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

        api_path = '/help_center/articles/%s/translations/%s.json' % (article['id'], language)

        zendesk_json_request(domain, api_path, 'translation', 'PUT', json_params)

    return True