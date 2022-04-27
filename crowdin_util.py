from bs4 import BeautifulSoup
import git
import logging
import random
import requests
from scrape_liferay import authenticate, session
import urllib

csrf_token = ''.join([random.choice('0123456789abcdefghijklmnopqrstuvwxyz') for x in range(10)])

def crowdin_http_request(repository, path, method, **data):
    global csrf_token

    if method == 'GET':
        get_data = { key: value for key, value in data.items() }

        get_data['project_id'] = repository.crowdin.project_id
        get_data['target_language_id'] = '25'

        query_string = '&'.join([urllib.parse.quote(key) + '=' + urllib.parse.quote(str(value)) for key, value in get_data.items()])
        
        url = 'https://crowdin.com%s?%s' % (path, query_string)
    else:
        url = 'https://crowdin.com%s' % path

    session.cookies.set('csrf_token', csrf_token, domain='.crowdin.com', path='/')

    try:
        if method == 'GET':
            r = session.get(url, headers={'x-csrf-token': csrf_token})
        elif method == 'POST':
            r = session.post(url, data=data, headers={'x-csrf-token': csrf_token})

        if r.url.find('/login') == -1:
            return r.content
    except:
        pass
    
    logging.info('Session timed out, refreshing session')

    continue_url = 'https://crowdin.com/%s/settings' % repository.crowdin.project_name
    login_url = 'https://accounts.crowdin.com/login'

    r = session.get(login_url)
    
    soup = BeautifulSoup(r.text, features='html.parser')
    token_input = soup.find('input', attrs={'name': '_token'})
    
    if token_input is None:
        return crowdin_http_request(repository, path, method, **data)
    
    login_data = {
        'email_or_login': git.config_prompt('crowdin.login', 'login'),
        'password': git.config_prompt('crowdin.password', 'password'),
        'hash': 'files',
        'continue': url,
        'locale': 'en',
        'intended': '/auth/token',
        '_token': token_input.attrs['value']
    }

    r = session.post(login_url, data=login_data)

    if r.text.find('/remember-me/decline') != -1:
        soup = BeautifulSoup(r.text, features='html.parser')
        token_input = soup.find('input', attrs={'name': '_token'})

        login_data = {
            '_token': token_input.attrs['value']
        }

        r = session.post('https://accounts.crowdin.com/remember-me/decline', data=login_data)

    return crowdin_http_request(repository, path, method, **data)

crowdin_base_url = 'https://api.crowdin.com/api'

def crowdin_request(repository, api_path, request_type='GET', data=None, files=None):
    headers = {
        'user-agent': 'python'
    }

    if repository is None:
        request_url = crowdin_base_url + api_path
    else:
        request_url = crowdin_base_url + '/project/' + repository.crowdin.project_name + api_path

    if repository is None:
        get_data = {
            'login': git.config_prompt('crowdin.account-login', 'API login'),
            'account-key': git.config_prompt('crowdin.account-key-v1', 'API key v1')
        }
    else:
        get_data = {
            'key': repository.crowdin.api_key
        }
    
    if request_type == 'GET':
        if data is not None:
            get_data.update(data)
            
        request_url = request_url + '?' + '&'.join([key + '=' + value for key, value in get_data.items()])

        r = requests.get(request_url, data=get_data, headers=headers)
    else:
        request_url = request_url + '?' + '&'.join([key + '=' + value for key, value in get_data.items()])

        r = requests.post(request_url, data=data, files=files, headers=headers)

    if r.status_code < 200 or r.status_code >= 400:
        logging.error('HTTP Error: %d' % r.status_code)
        return (r.status_code, None)

    return (r.status_code, r.content)

def extract_crowdin_file_info(repository, files_element, current_path, file_info):
    for item in files_element.children:
        if item.name != 'item':
            continue

        item_name = item.find('name').text
        item_node_type = item.find('node_type').text

        item_path = current_path + '/' + item_name if current_path is not None else item_name

        if item_path.find(repository.crowdin.dest_folder) == 0:
            file_info[item_path] = {
                'phrases': int(item.find('phrases').text),
                'translated': int(item.find('translated').text),
                'approved': int(item.find('approved').text)
            }

            if item_node_type == 'file':
                file_info[item_path]['id'] = item.find('id').text

        if item_node_type != 'file':
            extract_crowdin_file_info(repository, item.find('files'), item_path, file_info)

def get_crowdin_file_info(repository, target_language):
    if target_language.find('-') != -1:
        target_language = target_language[:target_language.find('-')]

    data = {
        'language': target_language
    }

    status_code, response_content = crowdin_request(
        repository, '/language-status', 'POST', data)

    file_info = {}

    if response_content is not None:
        soup = BeautifulSoup(response_content, features='html.parser')
        extract_crowdin_file_info(repository, soup.find('files'), None, file_info)

    return file_info