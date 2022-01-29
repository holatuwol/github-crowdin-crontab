from crowdin import crowdin_download_translations, crowdin_upload_sources, delete_code_translations, fix_product_name_tokens, get_crowdin_file_info, pre_translate, save_glossary, save_translation_memory
from datetime import datetime
from file_manager import get_crowdin_file, get_eligible_files, get_local_file, get_root_folders, get_translation_path
import git
from github import get_milestone_map, get_milestone_numbers, init_issues, update_translation_issues
import logging
import os
import re
from repository import initial_dir

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')

# Perform any needed GitHub issue maintenance to keep project boards usable,
# perform any needed CrowdIn file maintenance to stay under the quota.

def cleanup_files(repository, source_language, target_language, all_files, old_file_info, new_file_info):
    human_milestone_number = get_milestone_map(repository)['human']
    milestone_numbers = get_milestone_numbers(repository, all_files, new_file_info)

    new_keys = set(new_file_info.keys()).difference(set(old_file_info.keys()))

    to_delete = set()
    to_upload = set()

    for key, metadata in new_file_info.items():
        if 'id' not in metadata:
            continue

        if key.find(repository.crowdin.dest_folder) != 0:
            continue

        local_file = get_local_file(repository, key)
        root_folders = get_root_folders(repository, [local_file])
        
        if len(root_folders) == 0:
            continue
        
        folder = root_folders[0]

        if folder not in milestone_numbers:
            continue

        state, milestone_number = milestone_numbers[folder]

        if milestone_number != human_milestone_number:
            to_delete.add(key)
        elif key in new_keys:
            to_upload.add(local_file)

    return update_sources(repository, source_language, target_language, to_upload)

def update_sources(repository, source_language, target_language, new_files, all_files):
    old_file_info, file_info = crowdin_upload_sources(repository, source_language, target_language, new_files)

    update_files = set(new_files)

    file_info = pre_translate(repository, source_language, target_language, update_files, all_files, file_info)

    crowdin_download_translations(repository, source_language, target_language, all_files, file_info)

    return old_file_info, file_info

# Retrieve the list of all files we should translate and all updated files that
# we need to re-translate.

def get_branch_files(repository, source_language, check_upstream=False):
    if check_upstream and repository.github.upstream is not None:
        git.fetch(
            'upstream', '--no-tags', '%s:refs/remotes/upstream/%s' % \
                (repository.github.branch, repository.github.branch))

        diff_output = git.diff(
            '--name-only', 'origin/%s..upstream/%s' % \
                (repository.github.branch, repository.github.branch),
            strip=False)

        git.rebase('upstream/%s' % repository.github.branch)
    else:
        diff_output = '\n'.join([
            line[3:] for line in git.status('status', '-s', strip=False) if len(line) > 3
        ])

    new_files = get_eligible_files(repository, diff_output, source_language)

    lstree_output = git.ls_tree('-r', '--name-only', repository.github.branch, strip=False)
    all_files = get_eligible_files(repository, lstree_output, source_language)

    return new_files, all_files

# Update local copies of translations, translation memory, and glossaries.

def get_repository_state(repository, source_language, target_language, refresh_paths=None, check_upstream=False):
    global git_root
    git_root = repository.github.git_root
    
    logging.info('cd %s' % git_root)
    os.chdir(git_root)

    if refresh_paths is None:
        new_files, all_files = get_branch_files(repository, source_language, check_upstream)
    else:
        new_files = refresh_paths
        _, all_files = get_branch_files(repository, source_language, check_upstream)

    file_info = get_crowdin_file_info(repository, target_language)

    return new_files, all_files, file_info

def check_file_lists(repository, source_language, target_language, new_files, all_files):
    for file in all_files:
        if not os.path.exists(file):
            continue

        with open(file, 'r') as f:
            file_content = f.read()

        if re.search('@[^@ ]*-[^@ ]*@', file_content) is None:
            continue

        target_file = get_translation_path(file, source_language, target_language)

        if not os.path.exists(target_file):
            continue

        with open(target_file, 'r') as f:
            file_content = f.read()

        if file_content.find('@<') == -1 and file_content.find('>@') == -1:
            continue
        
        if file not in new_files:
            new_files.append(file)

    for file in set(all_files) - set(new_files):
        target_file = get_translation_path(file, source_language, target_language)

        if not os.path.isfile(target_file):
            new_files.append(file)

def update_repository(repository, source_language, target_language, refresh_paths=None, check_upstream=False, create_issues=False, sync_sources=True):
    step_number = 1

    logging.info('step %d: get repository state for translation download' % step_number)
    step_number = step_number + 1

    new_files, all_files, file_info = get_repository_state(repository, source_language, target_language, refresh_paths, check_upstream)

    if not sync_sources:
        all_files = []

        for crowdin_file, metadata in file_info.items():
            if 'id' in metadata:
                local_file = get_local_file(repository, crowdin_file)
                local_folder = os.path.dirname(local_file)

                if not os.path.isdir(local_folder):
                    os.makedirs(local_folder)

                all_files.append(local_file)

        new_files = all_files

    logging.info('step %d: check for existing translations of %d files' % (step_number, len(all_files)))
    step_number = step_number + 1

    check_file_lists(repository, source_language, target_language, new_files, all_files)

    if sync_sources:
        logging.info('step %d: add %d source files to crowdin' % (step_number, len(new_files)))

        old_file_info, file_info = update_sources(repository, source_language, target_language, new_files, all_files)
    else:
        logging.info('step %d: check for translations of %d source files' % (step_number, len(new_files)))

        crowdin_download_translations(repository, source_language, target_language, all_files, file_info)

        old_file_info = file_info

    if create_issues:
        logging.info('step %d: generate github issues' % step_number)
        step_number = step_number + 1

        init_issues(repository, all_files, file_info)

    logging.info('step %d: add updated translations to github' % step_number)
    step_number = step_number + 1

    if create_issues:
        logging.info('step %d: update github project' % step_number)
        step_number = step_number + 1

        update_translation_issues(repository, file_info)

    logging.info('cd -')
    os.chdir(initial_dir)
    
    return new_files, all_files, file_info