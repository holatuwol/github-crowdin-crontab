from bs4 import BeautifulSoup
from collections import namedtuple
import json
import logging
import onepass
import os
import pandas as pd
import pickle
import random
import requests
from session import initial_dir, session

# Retrieve information from 1password

username = onepass.item('Crowdin', 'username')['username']
password = onepass.item('Crowdin', 'password')['password']

if username[0] == '"' and username[-1] == '"':
    username = username[1:-1]

if password[0] == '"' and password[-1] == '"':
    password = password[1:-1]

bearer_token = onepass.item('Crowdin Account Key v2', 'credential')['credential']

# Generate a random CSRF token

x_csrf_token = ''.join([random.choice('0123456789abcdefghijklmnopqrstuvwxyz') for x in range(10)])
session.cookies.set('csrf_token', x_csrf_token, domain='crowdin.com', path='/')

CrowdInRepository = namedtuple(
    'CrowdinRepository',
    ' '.join(['git_root', 'git_folder', 'source_language', 'project_id', 'project_name', 'api_key', 'dest_folder', 'single_folder'])
)

def get_repository_helper(projects, source_language, git_repository, git_folder, project_id, project_name, project_folder):
    crowdin_single_folder = project_folder
    
    git_root = os.path.dirname(initial_dir) + '/' + git_repository

    if not os.path.isdir(git_root):
        return None

    project_api_keys = [project['key'] if 'key' in project else None for project in projects if project['identifier'] == project_name]

    if len(project_api_keys) == 0:
        project_api_key = None
    else:
        project_api_key = project_api_keys[0]

    return CrowdInRepository(git_root, git_folder, source_language, project_id, project_name, project_api_key, project_folder, crowdin_single_folder)

def get_repositories():
    projects = []

    repositories_df = pd.read_csv('%s/repositories.csv' % initial_dir, comment='#')

    for project_id in repositories_df['project_id'].unique():
        status_code, response_data = crowdin_request('/projects/%s' % project_id, 'GET')
        projects.append(response_data)

    repositories = [get_repository_helper(projects, **x) for x in repositories_df.to_dict('records')]

    return [x for x in repositories if x is not None]

def get_repository(domain):
	all_repositories = get_repositories()
	return [x for x in all_repositories if x.dest_folder == domain][0]

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

def get_repository_state(repository, source_language, target_language):
    global git_root
    git_root = repository.git_root
    
    logging.info('cd %s' % git_root)
    os.chdir(git_root)

    file_info = get_crowdin_file_info(repository, target_language)

    all_files = [
        get_local_file(repository, crowdin_file)
            for crowdin_file, metadata in file_info.items()
                if 'id' in metadata and crowdin_file.find(repository.dest_folder) == 0
    ]

    all_files = sorted(set(all_files))

    return all_files, all_files, file_info

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

    api_path = crowdin_base_url + '/v2/storages'

    with open(file_path, 'rb') as f:
        r = requests.post(api_path, data=f.read(), headers=headers)

    if r.status_code == 401:
        logging.error('Invalid user name or password')
        return (r.status_code, None)

    if r.status_code >= 400:
        logging.error('HTTP Error: %s' % r.content)
        return (r.status_code, None)

    if r.status_code < 200:
        logging.error('HTTP Error: %d' % r.status_code)
        return (r.status_code, None)

    response = json.loads(r.content)
    return (r.status_code, response['data'])

def get_directory(repository, path, create_if_missing=True):
    path = repository.dest_folder if len(path) == 0 else '/%s/%s' % (repository.dest_folder, path)

    logging.info('Looking up CrowdIn directory for path %s...' % path)

    pagination_data = {
        'offset': 0,
        'limit': 500
    }

    api_path = '/projects/%s/directories' % repository.project_id
    status_code, response_data = crowdin_request(api_path, 'GET', {})

    directories = {
        directory['data']['id']: directory['data']
            for directory in response_data
    }

    directory_paths = {}

    for directory in directories.values():
        path_elements = []

        parent_directory = directory

        while parent_directory is not None:
            path_elements.append(parent_directory['name'])

            if parent_directory['directoryId'] is None:
                parent_directory = None
            else:
                parent_directory = directories[parent_directory['directoryId']]

        path_elements.reverse()

        directory_path = '/' + '/'.join(path_elements)

        directory_paths[directory_path] = directory

    if path in directory_paths:
        return directory_paths[path]

    if not create_if_missing:
        return None

    parent_path = os.path.dirname(path)

    while parent_path not in directory_paths and parent_path != '/' and parent_path != '':
        parent_path = os.path.dirname(parent_path)

    if parent_path == '':
        parent_directory = None
        path_elements = path.split('/')
    elif parent_path == '/':
        parent_directory = None
        path_elements = path[1:].split('/')
    else:
        parent_directory = directory_paths[parent_path]
        path_elements = path[len(parent_path)+1:].split('/')

    for i, name in enumerate(path_elements):
        parent_path = '/' + '/'.join(path_elements[:i+1])

        if parent_path in directory_paths:
            parent_directory = directory_paths[parent_path]
            continue

        logging.info('Creating subdirectory %s', parent_path)

        data = {
            'name': name,
        }

        if parent_directory is not None:
            data['directoryId'] = parent_directory['id']

        status_code, parent_directory = crowdin_request(api_path, 'POST', data)

    return parent_directory

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

    api_path = '/projects/%s/files' % repository.project_id

    status_code, response_data = crowdin_request(
        api_path, 'GET', pagination_data)

    for item in response_data:
        item_path = item['data']['path'] if repository.dest_folder[0] == '/' else item['data']['path'][1:]
        item_paths[item['data']['id']] = item_path

        pos = item_path.find(repository.dest_folder)

        if pos == 0:
            file_info[item_path] = item['data']

    logging.info('Found %d/%d files matching destination folder %s' % (len(file_info), len(response_data), repository.dest_folder))

    # Fetch the list of translation statuses

    pagination_data['offset'] = 0
    api_path = '/projects/%s/languages/%s/progress' % (repository.project_id, target_language)

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

def get_crowdin_file(repository, local_file):
    if local_file.find(repository.git_folder) == 0:
        return repository.dest_folder + '/' + local_file[len(repository.git_folder)+1:]

    return None

def get_local_file(repository, crowdin_file):
    if crowdin_file.find(repository.dest_folder) == 0:
        return repository.git_folder + crowdin_file[len(repository.dest_folder):]

    return None

def get_translation_path(file, source_language, target_language):
    source_language_path = source_language

    if source_language.find('-') != -1:
        source_language_path = source_language[:source_language.find('-')]

    target_language_path = target_language

    if target_language.find('-') != -1:
        target_language_path = target_language[:target_language.find('-')]

    if file[0:3] == '%s/' % source_language_path:
        return '%s/%s' % (target_language_path, file[3:])
    else:
        return file.replace('/%s/' % source_language_path, '/%s/' % target_language_path)