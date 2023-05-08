from crowdin_util import crowdin_http_request, crowdin_request, get_crowdin_file_info
import git
import json
import logging
import pandas as pd
from repository import CrowdInRepository, TranslationRepository
import requests
import sys

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
    repository = TranslationRepository(None, CrowdInRepository(source_language, project_id, project_name, None, project_folder, False, False))

    file_info = get_crowdin_file_info(repository, target_language)

    for file_name, file_metadata in file_info.items():
        api_path = '/projects/%s/languages/%s/translations' % (repository.crowdin.project_id, target_language)

        pagination_data = {
            'fileId': file_metadata['id'],
            'offset': 0,
            'limit': 500
        }

        status_code, response_data = crowdin_request(api_path, 'GET', pagination_data)

        for item in response_data:
            if is_malformed_translation(item['data']['text']):
                print('https://crowdin.com/translate/liferay-japan-documentation/%s/en-%s#%s' % (file_metadata['id'], target_language, item['data']['stringId']))
                print(item['data']['text'])
                print()

if __name__ == '__main__':
    check_pre_translations(*sys.argv[1:])