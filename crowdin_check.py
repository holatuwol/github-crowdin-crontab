from crowdin_util import crowdin_http_request, crowdin_request, get_crowdin_file_info
import git
import json
import logging
import pandas as pd
from repository import CrowdInRepository, TranslationRepository
import requests
import sys

user_id = None
crowdin_base_url = 'https://api.crowdin.com/api'

def crowdin_request_v2(repository, api_path, request_type='GET', data={}, files=None):
    global user_id

    headers = {
        'user-agent': 'python',
        'authorization': 'Bearer %s' % git.config_prompt('crowdin.account-key-v2', 'https://crowdin.com/settings#api-key "Account API key"')
    }

    if user_id is None and api_path != '/user':
        status_code, response_data = crowdin_request_v2(None, '/user', 'GET')
        user_id = response_data['id']

    request_url = crowdin_base_url + '/v2' + api_path

    if request_type == 'GET':
        request_url = request_url + '?' + '&'.join([key + '=' + str(value) for key, value in data.items()])

        r = requests.get(request_url, headers=headers)
    else:
        r = requests.post(request_url, json=data, headers=headers)

    if r.status_code == 401 or r.status_code == 404:
        logging.error('Invalid user name or password')

        git.config('--global', '--unset', 'crowdin.account-key-v2')

        return crowdin_request_v2(repository, api_path, request_type, data, files)

    if r.status_code >= 400:
        logging.error('HTTP Error: %s' % r.content)
        return (r.status_code, None)

    if r.status_code < 200:
        logging.error('HTTP Error: %d' % r.status_code)
        return (r.status_code, None)

    return (r.status_code, json.loads(r.content)['data'])

def get_crowdin_file_info_v2(repository, target_language):
    if target_language[0:2] == 'ja':
        target_language = 'ja'

    file_info = {}
    item_paths = {}

    pagination_data = {
        'offset': 0,
        'limit': 500
    }

    # Fetch the list of files

    api_path = '/projects/%s/files' % repository.crowdin.project_id

    while True:
        status_code, response_data = crowdin_request_v2(
            repository, api_path, 'GET', pagination_data)

        for item in response_data:
            item_path = item['data']['path']
            item_paths[item['data']['id']] = item_path

            pos = item_path.find(repository.crowdin.dest_folder)

            if pos == 0 or pos == 1:
                file_info[item_path] = item['data']

        if len(response_data) < 500:
            break

        pagination_data['offset'] = pagination_data['offset'] + 500

    # Fetch the list of translation statuses

    pagination_data['offset'] = 0
    api_path = '/projects/%s/languages/%s/progress' % (repository.crowdin.project_id, target_language)

    while True:
        status_code, response_data = crowdin_request_v2(
            repository, api_path, 'GET', pagination_data)

        for item in response_data:
            item_path = item_paths[item['data']['fileId']]

            if item_path in file_info:
                file_info[item_path]['phrases'] = item['data']['phrases']['total']
                file_info[item_path]['translated'] = item['data']['phrases']['translated']
                file_info[item_path]['approved'] = item['data']['phrases']['approved']

        if len(response_data) < 500:
            break

        pagination_data['offset'] = pagination_data['offset'] + 500

    return file_info

valid_tag_chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ:_-'

def is_malformed_translation(text):
    open_tags = []

    i = 0
    max_i = len(text)

    while i < max_i:
        if text[i] != '<':
            i = i + 1
            continue

        if text[i+1] == '/':
            if len(open_tags) == 0:
                return True

            j = i + 2

            while j < max_i:
                if text[j] in valid_tag_chars:
                    j = j + 1
                    continue

                tag_name = text[i+2:j]
                if tag_name != open_tags[-1]:
                    return True

                open_tags.pop()
                break

            i = j + 1
        else:
            j = i + 1

            while j < max_i:
                if text[j] in valid_tag_chars:
                    j = j + 1
                    continue

                tag_name = text[i+1:j]
                open_tags.append(tag_name)
                break

            i = j + 1

    return False

def check_pre_translations(project_id, project_name, project_folder, source_language, target_language, force=False):
    repository = TranslationRepository(None, CrowdInRepository(project_id, project_name, None, project_folder, False, False))

    file_info = get_crowdin_file_info_v2(repository, target_language)

    for file_name, file_metadata in file_info.items():
        api_path = '/projects/%s/languages/%s/translations' % (repository.crowdin.project_id, target_language)

        pagination_data = {
            'fileId': file_metadata['id'],
            'offset': 0,
            'limit': 500
        }

        while True:
            status_code, response_data = crowdin_request_v2(
                repository, api_path, 'GET', pagination_data)

            for item in response_data:
                if is_malformed_translation(item['data']['text']):
                    print('https://crowdin.com/translate/liferay-japan-documentation/%s/en-%s#%s' % (file_metadata['id'], target_language, item['data']['stringId']))
                    print(item['data']['text'])
                    print()

            if len(response_data) < 500:
                break

            pagination_data['offset'] = pagination_data['offset'] + 500

if __name__ == '__main__':
    check_pre_translations(*sys.argv[1:])