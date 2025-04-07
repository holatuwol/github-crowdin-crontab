from bs4 import BeautifulSoup
from http.client import HTTPConnection
import inspect
import json
import logging
import os
import pickle
import random
import requests
import sys
import urllib

script_root_folder = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
faster_deploy_folder = os.path.join(os.path.dirname(script_root_folder), 'liferay-faster-deploy')

sys.path.insert(0, faster_deploy_folder)

import git
import onepass
from patcher.scrape_liferay import session




# Retrieve information from 1password

crowdin_config = git.config('1password.crowdin')

if crowdin_config is None:
    username = input('https://crowdin.com/settings#account "Username"')
    password = input('https://crowdin.com/settings#password "Password"')
else:
    username = onepass.item(crowdin_config, 'username')['username']
    password = onepass.item(crowdin_config, 'password')['password']

if username[0] == '"' and username[-1] == '"':
    username = username[1:-1]

if password[0] == '"' and password[-1] == '"':
    password = password[1:-1]

crowdin_config = git.config('1password.crowdin-api-v2')

if crowdin_config is None:
    bearer_token = input('https://crowdin.com/settings#api-key "Account API key"')
else:
    bearer_token = onepass.item(crowdin_config, 'credential')['credential']

# Generate a random CSRF token

x_csrf_token = ''.join([random.choice('0123456789abcdefghijklmnopqrstuvwxyz') for x in range(10)])
session.cookies.set('csrf_token', x_csrf_token, domain='crowdin.com', path='/')

def crowdin_authenticate(path):
    login_url = 'https://accounts.crowdin.com/login'

    r = session.get(login_url)

    soup = BeautifulSoup(r.text, features='html.parser')

    token_input = soup.find('input', attrs={'name': '_token'})

    if token_input is None:
        return True

    csrf_token = token_input.attrs['value']

    login_data = {
        'email_or_login': username,
        'password': password,
        'continue': path,
        'domain': '',
        'locale': 'en',
        'intended': '/auth/token',
        '_token': csrf_token
    }

    r = session.post(login_url, data=login_data)

    while r.text.find('resend_device_verification_code') != -1:
        soup = BeautifulSoup(r.text, features='html.parser')

        token_input = soup.find('input', attrs={'name': '_token'})
        csrf_token = token_input.attrs['value']
        session.cookies.set('CSRF-TOKEN', csrf_token, domain='crowdin.com', path='/')

        login_data = {
            'continue': path,
            'locale': 'en',
            'intended': '/auth/token',
            '_token': token_input.attrs['value'],
            'verification_code': input('verification code: ')
        }

        r = session.post('https://accounts.crowdin.com/device-verify/code', data=login_data, headers={'x-csrf-token': x_csrf_token})

    if r.text.find('/remember-me/decline') != -1:
        soup = BeautifulSoup(r.text, features='html.parser')

        token_input = soup.find('input', attrs={'name': '_token'})
        csrf_token = token_input.attrs['value']
        session.cookies.set('CSRF-TOKEN', csrf_token, domain='crowdin.com', path='/')

        login_data = {
            '_token': token_input.attrs['value']
        }

        r = session.post('https://accounts.crowdin.com/remember-me/decline', data=login_data, headers={'x-csrf-token': x_csrf_token})

    with open('session.ser', 'wb') as f:
        pickle.dump(session, f)

    return True

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
        'authorization': 'Bearer %s' % bearer_token,
        'accept': 'application/json',
    }

    if user_id is None and api_path != '/user':
        status_code, response_data = crowdin_request('/user', 'GET', {})
        user_id = response_data['id']

    request_url = crowdin_base_url + '/v2' + api_path

    if method == 'DELETE':
        r = requests.delete(request_url, params=data, headers=headers)
    elif method == 'GET':
        r = requests.get(request_url, params=data, headers=headers)
    elif method == 'PATCH':
        r = requests.patch(request_url, json=data, headers=headers)
    elif method == 'POST':
        r = requests.post(request_url, json=data, headers=headers)
    elif method == 'PUT':
        r = requests.put(request_url, json=data, headers=headers)
    else:
        raise Exception('Unrecognized method: %s' % method)

    if r.status_code == 204:
        return (status_code, None)

    if r.status_code == 401:
        logging.error('Invalid bearer token, please update')
        exit()

    if r.status_code >= 400:
        logging.error('HTTP Error: %s' % r.content)
        return (r.status_code, None)

    if r.status_code < 200:
        logging.error('HTTP Error: %d' % r.status_code)
        return (r.status_code, None)

    try:
        response = r.json()
    except:
        return (r.status_code, r.text)

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
        'authorization': 'Bearer %s' % bearer_token
    }

    if user_id is None:
        status_code, response_data = crowdin_request('/user', 'GET', {})
        user_id = response_data['id']

    request_url = crowdin_base_url + '/v2/storages'

    with open(file_path, 'rb') as f:
        r = requests.post(request_url, data=f.read(), headers=headers)

    if r.status_code == 401:
        logging.error('Invalid user name or password')

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

#HTTPConnection.debuglevel = 1
#crowdin_authenticate('/profile')