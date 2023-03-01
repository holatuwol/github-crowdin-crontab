from collections import defaultdict
from crowdin_hide import hide_code_translations
from crowdin_util import crowdin_http_request, crowdin_request, get_crowdin_file_info, upload_file_to_crowdin_storage
from datetime import datetime, timedelta
import git
from file_manager import get_crowdin_file, get_local_file, get_root_folders, get_translation_path
import json
import logging
import math
import os
import numpy as np
import pandas as pd
from repository import CrowdInRepository, TranslationRepository, initial_dir
import requests
import subprocess
import time
from zipfile import ZipFile

# Use "pandoc" to disable word wrapping to improve machine translations.

def _pandoc(source_file, target_file, *args):
    with open(source_file, 'r') as f:
        lines = f.readlines()

        title_pos = -1
        toc_pos = -1

        for i, line in enumerate(lines):
            if title_pos == -1 and line.find('#') == 0:
                title_pos = i
            elif line.find('[TOC') == 0:
                toc_pos = i

        if source_file == target_file:
            head_lines = ''.join(lines[0:max(title_pos, toc_pos)+1])
            tail_lines = ''.join(lines[max(title_pos, toc_pos)+1:])
        else:
            head_lines = None

            if title_pos == -1:
                tail_lines = ''.join(lines[max(title_pos, toc_pos)+1:])
            else:
                tail_lines = lines[title_pos] + '\n' + ''.join(lines[max(title_pos, toc_pos)+1:])

    cmd = ['pandoc'] + list(args)

    pipe = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = pipe.communicate(input=tail_lines.encode('UTF-8'))

    nowrap_lines = out.decode('UTF-8', 'replace')

    with open(target_file, 'w') as f:
        if head_lines is not None:
            f.write(head_lines)
            f.write('\n')

        f.write(nowrap_lines)

# Generate a "crowdin.yaml" file to tell the CLI what to do.

def get_crowdin_config_entry(repository, source_language, target_language, source_file):
    assert(not os.path.isdir(source_file))

    if source_language.find('-') != -1:
        source_language = source_language[:source_language.find('-')]

    if target_language.find('-') != -1:
        target_language = target_language[:target_language.find('-')]

    source_language_path = source_language + '/'

    if source_file[0:3] == source_language_path:
        target_language_path = target_language + '/'

        target_file = target_language_path + source_file[3:]
        translation = '%two_letters_code%/' + source_file[3:]
    else:
        source_language_path = '/' + source_language + '/'
        target_language_path = '/' + target_language + '/'

        target_file = source_file.replace(source_language_path, target_language_path)
        translation = source_file.replace(source_language_path, '/%two_letters_code%/')

    dest = '/' + get_crowdin_file(repository, source_file)

    os.makedirs(os.path.dirname(target_file), exist_ok=True)

    return {
        'source': source_file,
        'dest': dest,
        'translation': translation
    }

def fix_product_name_tokens(file):
    with open(file, 'r') as f:
        file_content = f.read()

    file_content = file_content.replace('@<', '@').replace('@>', '@')

    for token in ['@app-ref@', '@commerce', '@ide@', '@portal@', '@platform-ref@', '@product@', '@product-ver@']:
        file_content = file_content.replace('@ %s @' % (token[1:-1]), token)

    with open(file, 'w') as f:
        f.write(file_content)

# Wrapper functions to upload sources and download translations.

def get_directory(repository, path):
    path = '/%s/%s' % (repository.crowdin.dest_folder, path)

    pagination_data = {
        'offset': 0,
        'limit': 500
    }

    api_path = '/projects/%s/directories' % repository.crowdin.project_id
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

    parent_path = os.path.dirname(path)

    while parent_path not in directory_paths and parent_path != '/':
        parent_path = os.path.dirname(parent_path)

    parent_directory = directory_paths[parent_path]
    path_elements = path[len(parent_path)+1:].split('/')
    
    for i, name in enumerate(path_elements):
        logging.info('Looking up subdirectory %s', '/'.join(path_elements[:i+1]))

        data = {
            'name': name,
            'directoryId': parent_directory['id']
        }

        status_code, parent_directory = crowdin_request(api_path, 'POST', data)

    return parent_directory

def crowdin_upload_sources(repository, source_language, target_language, new_files):
    before_upload = get_crowdin_file_info(repository, target_language)

    for file in new_files:
        git.checkout(file)

        extension = file[file.rfind('.'):]

        if extension == '.md' or extension == '.markdown':
            _pandoc(file, file, '--from=gfm', '--to=gfm', '--wrap=none')

            fix_product_name_tokens(file)

    df = pd.read_csv('%s/ignore.csv' % initial_dir)
    ignore_files = set(df[df['repository'] == repository.github.upstream]['file'].values)
    upload_files = [file for file in new_files if file not in ignore_files]

    api_path = '/projects/%s/files' % repository.crowdin.project_id

    for i, file in enumerate(upload_files):
        logging.info('Preparing to upload file %d/%d...' % (i, len(upload_files)))

        directory = get_directory(repository, os.path.dirname(file))

        logging.info('Uploading file %d/%d...' % (i, len(upload_files)))

        status_code, response_data = upload_file_to_crowdin_storage(file)

        data = {
            'storageId': response_data['id'],
            'name': os.path.basename(file),
            'directoryId': directory['id']
        }

        logging.info('Telling crowdin about uploaded file %d/%d...' % (i, len(upload_files)))

        crowdin_request(api_path, 'POST', data)

    for file in new_files:
        git.checkout(file)

    if len(upload_files) > 0:
        after_upload = get_crowdin_file_info(repository, target_language)
    else:
        after_upload = before_upload
    
    return before_upload, after_upload

def crowdin_download_translations(repository, source_language, target_language, refresh_files, file_info):
    if source_language.find('-') != -1:
        source_language = source_language[:source_language.find('-')]

    if target_language.find('-') != -1:
        target_language = target_language[:target_language.find('-')]

    updated_files = list(refresh_files)

    api_path = '/projects/%s/directories' % repository.crowdin.project_id

    status_code, response_data = crowdin_request(api_path, 'GET', {})

    dest_directories = [directory['data'] for directory in response_data if directory['data']['name'] == repository.crowdin.dest_folder]

    if len(dest_directories) != 1:
        return

    dest_directory_id = dest_directories[0]['id']

    def get_recent_build(build_id):
        if build_id is not None:
            api_path = '/projects/%s/translations/builds/%s' % (repository.crowdin.project_id, build_id)

            status_code, response_data = crowdin_request(api_path, 'GET', {})

            if status_code == 200:
                build_id = response_data['id']

                return response_data

        api_path = '/projects/%s/translations/builds' % repository.crowdin.project_id

        logging.info('Retrieving build list...')
        status_code, response_data = crowdin_request(api_path, 'GET', {})

        for build in response_data:
            if 'directoryId' not in build['data'] or build['data']['directoryId'] != dest_directory_id:
                continue

            created_at = build['data']['createdAt']
            
            check_time = datetime.strptime(created_at[:-3] + created_at[-2:], '%Y-%m-%dT%H:%M:%S%z')
            min_time = datetime.now(check_time.tzinfo) - timedelta(minutes=30)

            if check_time > min_time:
                return build['data']

        return None

    recent_build = get_recent_build(None)

    if recent_build is None:
        api_path = '/projects/%s/translations/builds/directories/%s' % (repository.crowdin.project_id, dest_directory_id)

        data = {
            'targetLanguageIds': [target_language]
        }

        status_code, response_data = crowdin_request(api_path, 'POST', data)
        recent_build = response_data

    while recent_build['status'] != 'finished':
        logging.info('Waiting for build to finish...')
        time.sleep(15)
        recent_build = get_recent_build(recent_build['id'])

    api_path = '/projects/%s/translations/builds/%s/download' % (repository.crowdin.project_id, recent_build['id'])

    status_code, response_data = crowdin_request(api_path, 'GET', {})

    r = requests.get(response_data['url'])

    export_file_name = 'export-%f.zip' % datetime.utcnow().timestamp()

    logging.info('Downloading build from %s to %s' % (response_data['url'], export_file_name))

    with open(export_file_name, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    file_prefix = '%s/%s/' % (target_language, source_language)

    with ZipFile(export_file_name) as zipdata:
        for zipinfo in zipdata.infolist():
            if len(zipinfo.filename) <= len(file_prefix):
                continue
        
            if zipinfo.filename[:len(file_prefix)] != file_prefix:
                logging.info('Unexpected file name %s does not start with %s' % (zipinfo.filename, file_prefix))
                continue

            zipinfo.filename = '%s/%s' % (target_language, zipinfo.filename[len(file_prefix):])
            zipdata.extract(zipinfo, repository.github.git_root)

# Send requests to CrowdIn to do automated machine translation.

def translate_with_machine(repository, target_language, engine, file_ids):
    file_count = len(file_ids)

    update_api_path = '/projects/%s/pre-translations' % repository.crowdin.project_id

    for i, file_id in enumerate(file_ids.keys()):
        logging.info('crowdin-api pre-translate %s (%d/%d)' % (engine, i + 1, file_count))
        logging.info(file_ids[file_id])

        data = {
            'languageIds': [target_language],
            'method': 'tm' if engine == 'tm' else 'mt',
            'autoApproveOption': 'perfectMatchOnly',
            'fileIds': [file_id]
        }

        if engine != 'tm':
            data['engineId'] = engine

        status_code, response_data = crowdin_request(update_api_path, 'POST', data)

        status_api_path = '/projects/%s/pre-translations/%s' % (repository.crowdin.project_id, response_data['identifier'])

        while response_data['finishedAt'] is None:
            logging.info('Waiting for translation %d/%d to finish...' % (i + 1, file_count))
            time.sleep(5)
            status_code, response_data = crowdin_request(status_api_path, 'GET', {})

crowdin_request('/projects', 'GET', {})

def get_missing_phrases_files(repository, source_language, target_language, file_info):
    missing_phrases_files = {}

    for crowdin_file, metadata in file_info.items():
        if metadata['phrases'] != metadata['translated']:
            hide_code_translations(repository, source_language, target_language, crowdin_file, metadata)
            missing_phrases_files[metadata['id']] = crowdin_file

    return missing_phrases_files

def pre_translate(repository, source_language, target_language, all_files, file_info):
    # TM = translation memory
    missing_phrases_files = get_missing_phrases_files(repository, source_language, target_language, file_info)
    logging.info('%s files need to be updated using translation memory' % len(missing_phrases_files))
    translate_with_machine(repository, target_language, 'tm', missing_phrases_files)

    # 245660 = DeepL
    if target_language in ['en', 'ja']:
        file_info = get_crowdin_file_info(repository, target_language)
        missing_phrases_files = get_missing_phrases_files(repository, source_language, target_language, file_info)
        logging.info('%s files need to be updated using DeepL' % len(missing_phrases_files))
        translate_with_machine(repository, target_language, 245660, missing_phrases_files)

    # 213743 = Google Translate
    file_info = get_crowdin_file_info(repository, target_language)
    missing_phrases_files = get_missing_phrases_files(repository, source_language, target_language, file_info)
    logging.info('%s files need to be updated using Google Translate' % len(missing_phrases_files))
    translate_with_machine(repository, target_language, 213743, missing_phrases_files)

    return get_crowdin_file_info(repository, target_language)
