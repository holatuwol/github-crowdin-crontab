from bs4 import BeautifulSoup
import git
import json
import logging
import os
import pickle
import random
import requests
from scrape_liferay import authenticate, session
import urllib

csrf_token = ''.join([random.choice('0123456789abcdefghijklmnopqrstuvwxyz') for x in range(10)])
invalid_session = False

def crowdin_http_request(repository, path, method, **data):
    global csrf_token, invalid_session

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

    if invalid_session:
        git.config('--global', '--unset', 'crowdin.login')
        git.config('--global', '--unset', 'crowdin.password')
    else:
        logging.info('Session timed out, refreshing session')
        invalid_session = True

    continue_url = 'https://crowdin.com/%s/settings' % repository.crowdin.project_name
    login_url = 'https://accounts.crowdin.com/login'

    r = session.get(login_url)
    
    soup = BeautifulSoup(r.text, features='html.parser')
    token_input = soup.find('input', attrs={'name': '_token'})
    
    if token_input is None:
        return crowdin_http_request(repository, path, method, **data)
    
    login_data = {
        'email_or_login': git.config_prompt('crowdin.login', 'https://crowdin.com/settings#account "Username"'),
        'password': git.config_prompt('crowdin.password', 'https://crowdin.com/settings#password "Password"'),
        'hash': 'files',
        'continue': url,
        'locale': 'en',
        'intended': '/auth/token',
        '_token': token_input.attrs['value']
    }

    r = session.post(login_url, data=login_data)

    while r.text.find('resend_device_verification_code') != -1:
        soup = BeautifulSoup(r.text, features='html.parser')
        token_input = soup.find('input', attrs={'name': '_token'})

        login_data = {
            'continue': path,
            'locale': 'en',
            'intended': '/auth/token',
            '_token': token_input.attrs['value'],
            'verification_code': input('verification code: ')
        }

        r = session.post('https://accounts.crowdin.com/device-verify/code', data=login_data)

    if r.text.find('/remember-me/decline') != -1:
        soup = BeautifulSoup(r.text, features='html.parser')
        token_input = soup.find('input', attrs={'name': '_token'})

        login_data = {
            '_token': token_input.attrs['value']
        }

        r = session.post('https://accounts.crowdin.com/remember-me/decline', data=login_data)

    with open('session.ser', 'wb') as f:
        pickle.dump(session, f)

    return crowdin_http_request(repository, path, method, **data)

crowdin_base_url = 'https://api.crowdin.com/api'
user_id = None

def crowdin_request(api_path, method='GET', data=None, files=None):
    global user_id

    if data is None:
        data = {}

    offset = data['offset'] if 'offset' in data else 0
    limit = data['limit'] if 'limit' in data else 25

    print('%s (offset=%d)' % (api_path, offset))

    headers = {
        'user-agent': 'python',
        'authorization': 'Bearer %s' % git.config_prompt('crowdin.account-key-v2', 'https://crowdin.com/settings#api-key "Account API key"')
    }

    if user_id is None and api_path != '/user':
        status_code, response_data = crowdin_request('/user', 'GET', {})
        user_id = response_data['id']

    request_url = crowdin_base_url + '/v2' + api_path

    if method == 'GET':
        request_url = request_url + '?' + '&'.join([key + '=' + str(value) for key, value in data.items()])

        r = requests.get(request_url, headers=headers)
    elif method == 'POST':
        r = requests.post(request_url, json=data, headers=headers)
    elif method == 'PUT':
        r = requests.put(request_url, json=data, headers=headers)
    else:
        raise 'Unrecognized method: %s' % method

    if r.status_code == 401:
        logging.error('Invalid user name or password')

        git.config('--global', '--unset', 'crowdin.account-key-v2')

        return crowdin_request(api_path, method, data, files)

    if r.status_code >= 400:
        logging.error('HTTP Error: %s' % r.content)
        return (r.status_code, None)

    if r.status_code < 200:
        logging.error('HTTP Error: %d' % r.status_code)
        return (r.status_code, None)

    response = json.loads(r.content)
    response_data = response['data']

    if method != 'GET' or 'pagination' not in response or offset != 0:
        return (r.status_code, response_data)

    status_code = r.status_code

    results = []
    results.extend(response_data)

    while len(response_data) == limit:
        offset = offset + limit
        data['offset'] = offset
        data['limit'] = limit

        status_code, response_data = crowdin_request(api_path, method, data, files)
        results.extend(response_data)

    return (status_code, results)

def upload_file_to_crowdin_storage(file_path):
    global user_id

    headers = {
        'user-agent': 'python',
        'content-type': 'application/octet-stream',
        'Crowdin-API-FileName': os.path.basename(file_path),
        'authorization': 'Bearer %s' % git.config_prompt('crowdin.account-key-v2', 'https://crowdin.com/settings#api-key "Account API key"')
    }

    if user_id is None:
        status_code, response_data = crowdin_request('/user', 'GET', {})
        user_id = response_data['id']

    request_url = crowdin_base_url + '/v2/storages'

    with open(file_path, 'rb') as f:
        r = requests.post(request_url, data=f.read(), headers=headers)

    if r.status_code == 401:
        logging.error('Invalid user name or password')

        git.config('--global', '--unset', 'crowdin.account-key-v2')

        return crowdin_request(api_path, 'GET', {}, files)

    if r.status_code >= 400:
        logging.error('HTTP Error: %s' % r.content)
        return (r.status_code, None)

    if r.status_code < 200:
        logging.error('HTTP Error: %d' % r.status_code)
        return (r.status_code, None)

    response = json.loads(r.content)
    return (r.status_code, response['data'])

def get_crowdin_file_info(repository, target_language):
    if target_language[0:2] == 'ja':
        target_language = 'ja'
    if target_language[0:2] == 'ko':
        target_language = 'ko'
    if target_language[0:2] == 'en':
        target_language = 'en'

    file_info = {}
    item_paths = {}

    pagination_data = {
        'offset': 0,
        'limit': 500
    }

    # Fetch the list of files

    api_path = '/projects/%s/files' % repository.crowdin.project_id

    status_code, response_data = crowdin_request(
        api_path, 'GET', pagination_data)

    for item in response_data:
        item_path = item['data']['path'] if repository.crowdin.dest_folder[0] == '/' else item['data']['path'][1:]
        item_paths[item['data']['id']] = item_path

        pos = item_path.find(repository.crowdin.dest_folder)

        if pos == 0:
            file_info[item_path] = item['data']

    logging.info('Found %d/%d files matching destination folder %s' % (len(file_info), len(response_data), repository.crowdin.dest_folder))

    # Fetch the list of translation statuses

    pagination_data['offset'] = 0
    api_path = '/projects/%s/languages/%s/progress' % (repository.crowdin.project_id, target_language)

    while True:
        status_code, response_data = crowdin_request(
            api_path, 'GET', pagination_data)

        for item in response_data:
            key = item['data']['fileId']

            if key not in item_paths:
                continue

            item_path = item_paths[key]

            if item_path in file_info:
                file_info[item_path]['phrases'] = item['data']['phrases']['total']
                file_info[item_path]['translated'] = item['data']['phrases']['translated']
                file_info[item_path]['approved'] = item['data']['phrases']['approved']

        if len(response_data) < 500:
            break

        pagination_data['offset'] = pagination_data['offset'] + 500

    return file_info