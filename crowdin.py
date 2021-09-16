from bs4 import BeautifulSoup
from collections import defaultdict
from datetime import datetime, timedelta
import git
from file_manager import get_crowdin_file, get_local_file, get_root_folders, get_translation_path
import json
import logging
import math
import os
import numpy as np
import pandas as pd
import random
from repository import initial_dir
import requests
from scrape_liferay import authenticate, session
import subprocess
import time
import urllib

next_export = None

def _crowdin(*args):
    global next_export

    crowdin_cli_jar = '/usr/lib/crowdin/crowdin-cli.jar'

    if not os.path.isfile(crowdin_cli_jar):
        crowdin_cli_jar = '/usr/local/bin/crowdin-cli.jar'

    cmd = ['java', '-Duser.dir=%s' % os.getcwd(), '-jar', crowdin_cli_jar] + list(args)

    if args[0] == 'download' and next_export is not None:
        sleep_time = (next_export - datetime.now()).total_seconds()

        if sleep_time > 0:
            logging.info('Waiting %d minutes for next available export slot' % (sleep_time / 60))
            time.sleep(sleep_time)

    run_cmd = ' '.join(cmd)

    logging.info(run_cmd)

    finish = subprocess.run([run_cmd], cwd=os.getcwd(), capture_output=True, shell=True)

    if finish.returncode == 0:
        result = finish.stdout.decode('UTF-8', 'replace').strip()
    else:
        result = None

    print(finish.stderr)

    if args[0] == 'download':
        next_export = datetime.now() + timedelta(minutes=40)

    return result

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

def configure_crowdin(repository, source_language, target_language, files):
    configs = [get_crowdin_config_entry(repository, source_language, target_language, file) for file in sorted(set(files))]
    config_json = json.dumps(configs, indent=2)

    with open('%s/crowdin.yaml' % repository.github.git_root, 'w') as f:
        f.write('''
"project_identifier" : "{crowdin_project_name}"
"api_key" : "{crowdin_api_key}"
"base_path" : "{git_root}"
"preserve_hierarchy": true

"files": {files}
'''.format(
        crowdin_project_name=repository.crowdin.project_name,
        crowdin_api_key=repository.crowdin.api_key,
        git_root=repository.github.git_root,
        files=config_json
    ))

def fix_product_name_tokens(file):
    with open(file, 'r') as f:
        file_content = f.read()

    file_content = file_content.replace('@<', '@').replace('@>', '@')

    for token in ['@app-ref@', '@commerce', '@ide@', '@portal@', '@platform-ref@', '@product@', '@product-ver@']:
        file_content = file_content.replace('@ %s @' % (token[1:-1]), token)

    with open(file, 'w') as f:
        f.write(file_content)

# Wrapper functions to upload sources and download translations.

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

    if len(upload_files) > 0:
        configure_crowdin(repository, source_language, target_language, upload_files)

        _crowdin('upload', 'sources')

    for file in new_files:
        git.checkout(file)

    if len(upload_files) > 0:
        after_upload = get_crowdin_file_info(repository, target_language)
    else:
        after_upload = before_upload
    
    return before_upload, after_upload

def crowdin_download_translations(repository, source_language, target_language, refresh_files, file_info):
    if target_language.find('-') != -1:
        target_language = target_language[:target_language.find('-')]

    updated_files = list(refresh_files)

    for file in refresh_files:
        crowdin_file = get_crowdin_file(repository, file)

        if crowdin_file not in file_info:
            continue

        metadata = file_info[crowdin_file]
        updated_files.append(file)

        target_file = get_translation_path(file, source_language, target_language)

        if not os.path.isfile(target_file):
            updated_files.append(file)
            continue

    if len(updated_files) > 0:
        configure_crowdin(repository, source_language, target_language, updated_files)

        #_crowdin('download', '-l', target_language)

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
            'login': git.config('crowdin.account-login'),
            'account-key': git.config('crowdin.account-key-v1')
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

def save_translation_memory(repository, source_language, target_language):
    logging.info('crowdin-api download-tm')

    data = {
        'source_language': source_language,
        'target_language': target_language
    }

    status_code, response_content = crowdin_request(repository, '/download-tm', 'GET', data)

    if response_content is not None:
        with open('%s/%s.tmx' % (initial_dir, repository.crowdin.project_name), 'wb') as f:
            f.write(response_content)

def save_glossary(repository):
    logging.info('crowdin-api download-glossary')

    status_code, response_content = crowdin_request(repository, '/download-glossary', 'GET')

    if response_content is not None:
        with open('%s/%s.tbx' % (initial_dir, repository.crowdin.project_name), 'wb') as f:
            f.write(response_content)

def delete_translation(repository, file):
    logging.info('crowdin-api delete-file %s' % file)

    data = {
        'file': file
    }

    return crowdin_request(repository, '/delete-file', 'POST', data)

def delete_translation_folder(repository):
    folder = repository.crowdin.single_folder

    logging.info('crowdin-api delete-directory %s' % folder)

    data = {
        'name': folder
    }

    return crowdin_request(repository, '/delete-directory', 'POST', data)

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

# Send requests to CrowdIn to do automated machine translation.

def wait_for_translation(repository):
    while True:
        response = crowdin_http_request(
            repository, '/backend/project_actions/pre_translate_progress', 'GET')

        response_text = response.decode('utf-8')

        try:
            response_data = json.loads(response_text)

            if 'success' not in response_data or not response_data['success']:
                return

            if 'progress' not in response_data or response_data['progress'] == 100:
                return

            logging.info('crowdin-api pre-translate progress %d%%' % response_data['progress'])
        except:
            print(response_text)

            return

        time.sleep(5)

def translate_with_machine(repository, engine, file_ids):
    file_count = len(file_ids)

    for i, file_id in enumerate(file_ids.keys()):
        logging.info('crowdin-api pre-translate %s (%d/%d)' % (engine, i + 1, file_count))
        print(file_ids[file_id])

        data = {
            'project_id': repository.crowdin.project_id,
            'engine': engine,
            'approve_translated': '0',
            'auto_approve_option': '0',
            'apply_untranslated_strings_only': '1',
            'match_relevance': '0',
            'languages_list': '25',
            'files_list': file_id
        }

        response = crowdin_http_request(
            repository, '/backend/project_actions/pre_translate', 'POST', **data)

        response_text = response.decode('utf-8')

        try:
            response_data = json.loads(response_text)
        except:
            print(response_text)

        if response_data['success']:
            wait_for_translation(repository)

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
        'email_or_login': git.config('crowdin.login'),
        'password': git.config('crowdin.password'),
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

# Mass delete suggestions

def process_suggestions(repository, crowdin_file_name, file_info, translation_filter, translation_post_process, suggestion_filter):
    file_id = file_info[crowdin_file_name]['id']

    response_content = crowdin_http_request(
        repository, '/backend/phrases/phrases_as_html', 'GET',
        file_id=file_id)

    soup = BeautifulSoup(response_content, features='html.parser')   

    translations = [
        tag for tag in soup.find_all(attrs={'class': 'crowdin_phrase'})
    ]

    translation_ids = [
        tag.attrs['id'][len('crowdin_phrase_'):] for tag in translations
            if translation_filter(tag)
    ]

    has_suggestions = False

    for translation_id in translation_ids:
        response_content = crowdin_http_request(
            repository, '/backend/translation/phrase', 'GET',
            translation_id=translation_id)
        response_data = None

        try:
            response_data = json.loads(response_content.decode('utf-8'))['data']
            raw_suggestions = response_data['suggestions']
        except:
            logging.error('Error trying to parse phrase %s for file %s' % (translation_id, crowdin_file_name))
            raw_suggestions = []

        if type(raw_suggestions) is dict:
            suggestions = [
                suggestion for key, sublist in raw_suggestions.items() for suggestion in sublist
                    if suggestion_filter(suggestion)
            ]
        elif type(raw_suggestions) is list:
            suggestions = [
                suggestion for suggestion in raw_suggestions
                    if suggestion_filter(suggestion)
            ]
        else:
            logging.info('Unable to find translation %s for file %s' % (translation_id, file_name))
            suggestions = []

        if len(suggestions) > 0:
            has_suggestions = True

            for suggestion in suggestions:
                logging.info('Deleting suggestion %s from user %s' % (suggestion['id'], suggestion['user']['login']))
                crowdin_http_request(
                    repository, '/backend/suggestions/delete', 'GET',
                    translation_id=translation_id, plural_id='-1', suggestion_id=suggestion['id'])

        if translation_post_process is not None and response_data is not None:
            translation_post_process(translation_id, response_data)

    return has_suggestions

# Clear out auto-translations so we have a better sense of progress

def delete_auto_translations(repository, file_info):
    for crowdin_file_name in [key for key, value in file_info.items() if key.find(repository.crowdin.dest_folder) == 0 and 'id' in value]:
        logging.info('Removing auto-translations for file %s' % crowdin_file_name)

        process_suggestions(
            repository, crowdin_file_name, file_info,
            lambda x: True,
            None,
            lambda x: x['user']['login'] == 'is-user')

def delete_code_translations(repository, source_language, target_language, file_name, file_info):
    crowdin_file_name = get_crowdin_file(repository, file_name)
    
    if crowdin_file_name not in file_info:
        return False

    logging.info('Checking auto code translations for file %s' % file_name)

    def is_within_code_tag(x):
        return x.text and x.text.find('[TOC') == 0 or \
            x.text and x.text.find('CVSS') != -1 and x.text.find('CVE') != -1 or \
            x.name == 'code' or x.name == 'pre' or \
            x.find_parent('code') is not None or x.find_parent('pre') is not None or \
            x.find_parent(attrs={'id': 'front-matter'}) is not None

    def is_rst_directive(x):
        return x.text and ( \
            x.text.find('====') != -1 or x.text.find('----') != -1 or \
            x.text == '..' or x.text.find('::') != -1 or x.text.find(':') == 0 or \
            x.text.find(':doc:') != -1 or x.text.find(':ref:') != -1 or \
            x.text.lower() == x.text or \
            x.text[-3:] == '.md' or x.text[-4:] == '.rst' \
        )

    def hide_translation(translation_id, response_data):
        if not response_data['translation']['hidden']:
            crowdin_http_request(
                repository, '/backend/translation/change_visibility', 'GET',
                translation_id=translation_id, hidden=1)

    def always_true(x):
        return True

    def is_auto_translation(x):
        return x['user']['login'] == 'is-user'

    if file_name[-4:] == '.rst':
        has_suggestions = process_suggestions(
            repository, crowdin_file_name, file_info,
            is_rst_directive, hide_translation, always_true)
    else:
        has_suggestions = process_suggestions(
            repository, crowdin_file_name, file_info,
            is_within_code_tag, hide_translation, is_auto_translation)

    if not has_suggestions:
        return False

    target_file = get_translation_path(file, source_language, target_language)

    if os.path.exists(target_file):
        os.remove(target_file)

    return True

def get_file_ids(repository, files, file_info):
    candidate_files = {
        file: get_crowdin_file(repository, file) for file in files
    }

    return {
        file: file_info[crowdin_file]['id']
            for file, crowdin_file in candidate_files.items()
                if crowdin_file in file_info
    }

def pre_translate(repository, source_language, target_language, code_check_needed, translation_needed, file_info):
    code_check_needed_file_ids = get_file_ids(repository, code_check_needed, file_info)

    for file, crowdin_file in sorted(code_check_needed_file_ids.items()):
        file_metadata = file_info[get_crowdin_file(repository, file)]

        if file_metadata['phrases'] != file_metadata['translated']:
            delete_code_translations(repository, source_language, target_language, file, file_info)

    translation_needed_file_ids = get_file_ids(repository, translation_needed, file_info)

    missing_phrases_files = {}

    for file, crowdin_file in sorted(translation_needed_file_ids.items()):
        file_metadata = file_info[get_crowdin_file(repository, file)]

        if file_metadata['phrases'] != file_metadata['translated']:
            missing_phrases_files[crowdin_file] = crowdin_file
            print('%s (%s != %s)' % (file, file_metadata['phrases'], file_metadata['translated']))
        else:
            print('%s (%s == %s)' % (file, file_metadata['phrases'], file_metadata['translated']))

    if len(missing_phrases_files) > 0:
        #translate_with_machine(repository, 'tm', missing_phrases_files)
        translate_with_machine(repository, 'deepl-translator', missing_phrases_files)
        translate_with_machine(repository, 'google-translate', missing_phrases_files)

    file_info = get_crowdin_file_info(repository, target_language)
    
    return get_crowdin_file_info(repository, target_language)

def get_orphaned_files(repository, update_result):
    new_files, all_files, file_info = update_result

    crowdin_files = [
        key for key, value in file_info.items()
            if key.find(repository.crowdin.dest_folder) == 0 and 'id' in value
    ]

    local_files = [
        get_local_file(repository, key) for key in crowdin_files        
    ]

    deleted_files = [
        file for file in local_files if not os.path.isfile('%s/%s' % (repository.github.git_root, file))
    ]

    crowdin_rename_candidates = defaultdict(list)

    for file in crowdin_files:
        crowdin_rename_candidates[file[file.rfind('/')+1:]].append(file)

    deleted_file_candidates = {
        get_crowdin_file(repository, file): [
            candidate for candidate in crowdin_rename_candidates[file[file.rfind('/')+1:]]
                if candidate != get_crowdin_file(repository, file)
        ] for file in deleted_files
    }

    return [
        (key, value[0]) for key, value in deleted_file_candidates.items()
            if len(value) == 1
    ]

def get_orphaned_files_as_data_frame(repository, update_result):
    def get_data_row(file_info, file1, file2, columns):
        return [file1[file1.rfind('/')+1:]] + [
            file_info[file][column] for column in columns for file in [file1, file2]
        ]

    columns = ['id', 'translated', 'approved', 'phrases']

    return pd.DataFrame([
        get_data_row(file_info, file1, file2, columns)
            for file1, file2 in get_orphaned_files(repository, update_result)
    ], columns = ['name'] + ['%s%d' % (column, i) for column in columns for i in [1, 2]])

def delete_orphaned_files(repository, update_result):
    for file1, file2 in get_orphaned_files(repository, update_result):
        delete_translation(repository, file1)

