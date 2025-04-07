from bs4 import BeautifulSoup
from crowdin_util import crowdin_request, get_crowdin_file_info
import logging
import json
import os
import pandas as pd
from repository import CrowdInRepository, TranslationRepository
import sys

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')

# Mass delete suggestions

def show_translation(repository, project_id, string_id):
    crowdin_request('/projects/%s/strings/%s' % (project_id, string_id), 'PATCH', [{'op': 'replace', 'path': '/isHidden', 'value': False}])

def hide_translation(repository, project_id, string_id):
    crowdin_request('/projects/%s/strings/%s' % (project_id, string_id), 'PATCH', [{'op': 'replace', 'path': '/isHidden', 'value': True}])

# Clear out code translations

def hide_code_translations(repository, source_language, target_language, file_name, file_metadata):
    logging.info('Checking auto code translations for file %s' % file_name)

    project_id = repository.crowdin.project_id
    file_id = file_metadata['id']

    status_code, response_data = crowdin_request('/projects/%s/strings' % project_id, 'GET', {'fileId': file_id})

    for entry in response_data:
        is_hide_translation = entry['data']['context'].find('/pre') != -1 or entry['data']['context'].find('/code') != -1
        was_hidden_translation = entry['data']['isHidden']
        string_id = entry['data']['id']

        if is_hide_translation == was_hidden_translation:
            continue

        if is_hide_translation:
            hide_translation(repository, project_id, string_id)
        else:
            show_translation(repository, project_id, string_id)

    return False

def process_code_translations(project_id, project_name, project_folder, source_language, target_language, force=False):
    repository = TranslationRepository(None, CrowdInRepository(source_language, project_id, project_name, None, project_folder, False, False))

    file_info = get_crowdin_file_info(repository, target_language)

    for file_name, file_metadata in file_info.items():
        if force or 'id' in file_metadata and file_metadata['phrases'] != file_metadata['translated']:
            hide_code_translations(repository, source_language, target_language, file_name, file_metadata)

if __name__ == '__main__':
    process_code_translations(*sys.argv[1:])