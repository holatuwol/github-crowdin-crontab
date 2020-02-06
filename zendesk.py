import json
import logging
import math
from scrape_liferay import authenticate, session

def set_default_parameter(parameters, name, default_value):
    if name not in parameters:
        parameters[name] = default_value

# Create a method to make requests against the ZenDesk API, working around a
# bug in the ZenDesk incremental API: normally, API expects you to be able to
# continually use `next_page`. However, if you upload more than 1 page worth
# of entries within 1 second, the `next_page` becomes useless (this can happen
# if we bulk import articles via API, for example).

def zendesk_request(api_path, attribute_name, params=None):
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
        url = 'https://liferay-support.zendesk.com/api/v2%s?%s' % (api_path, query_string)

        if url is None:
            break

        r = session.get(url)
        logging.info(url)

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

def init_zendesk():
    logging.info('Authenticating with Liferay SAML IdP')
    authenticate('https://liferay-support.zendesk.com/access/login', None)
    
    return zendesk_request('/users/me.json', 'user')[0]

def get_zendesk_articles():
    user = init_zendesk()
    logging.info('Authenticated as %s' % user['email'])
    assert(user['verified'])

    # Reload the articles we already know about
    
    articles = {}

    try:
        with open('%s/articles.json' % initial_dir, 'r') as f:
            articles = json.load(f)
    except:
        pass
    
    # Fetch new articles with the incremental API
    
    article_parameters = {
        'start_time': 0 if len(articles) == 0 else max([article['updated_at'] for article in articles.values()])
    }
    
    new_articles = zendesk_request('/help_center/incremental/articles.json', 'articles', article_parameters)
    
    # Override past articles
    
    articles.update({article['id']: article for article in new_articles})
    
    # Cache the articles on disk so we can work on them without having to go back to the API
    
    with open('articles.json', 'w') as f:
        json.dump(articles, f)
    
    return articles

def update_zendesk_articles():
    user = init_zendesk()
    logging.info('Authenticated as %s' % user['email'])
    assert(user['verified'])

    # Determine the proper folder structure

    categories = zendesk_request('/help_center/en-us/categories.json', 'categories')
    category_paths = {
        category['id']: 'en/' + category['html_url'][category['html_url'].rfind('/'):]
            for category in categories
    }


    sections = zendesk_request('/help_center/en-us/sections.json', 'sections')
    section_paths = {
        section['id']: category_paths[section['category_id']] + section['html_url'][section['html_url'].rfind('/'):]
            for section in sections
    }
    
    articles = get_zendesk_articles()

    article_paths = {
        str(article['id']): section_paths[article['section_id']] + article['html_url'][article['html_url'].rfind('/'):] + '.html'
            for article in articles.values()
                if article['section_id'] in section_paths and not article['draft'] and article['locale'] == 'en-us' and 'Fast Track' not in article['label_names']
    }

    article_paths.update({
        str(article['id']): 'en/' + ('0'*12) + '-Fast-Track' + article['html_url'][article['html_url'].rfind('/'):] + '.html'
            for article in articles.values()
                if article['section_id'] in section_paths and not article['draft'] and article['locale'] == 'en-us' and 'Fast Track' in article['label_names']
    })

    for article_id, article_path in article_paths.items():
        article_file_name = '/home/minhchau/Work/liferay/zendesk-articles/%s' % article_path
        article_folder = os.path.dirname(article_file_name)

        if not os.path.exists(article_folder):
            os.makedirs(article_folder)

        with open(article_file_name, 'w', encoding='utf-8') as f:
            f.write(articles[article_id]['body'])

