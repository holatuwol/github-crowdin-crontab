from collections import defaultdict
from crowdin_util import crowdin_http_request, crowdin_request, get_crowdin_file_info
from datetime import datetime, timedelta
import git
from file_manager import get_crowdin_file, get_local_file, get_root_folders, get_translation_path
import json
import logging
import math
import os
import numpy as np
import pandas as pd
from repository import initial_dir
import subprocess
import time

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

