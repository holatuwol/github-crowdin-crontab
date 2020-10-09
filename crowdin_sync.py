from crowdin import crowdin_download_translations, crowdin_upload_sources, delete_code_translations, fix_product_name_tokens, get_crowdin_file_info, pre_translate, save_glossary, save_translation_memory
from datetime import datetime
from file_manager import get_crowdin_file, get_eligible_files, get_local_file, get_root_folders
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

def cleanup_files(repository, all_files, old_file_info, new_file_info):
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

    # if repository.crowdin.delete_enabled:
    #     for key in to_delete:
    #         delete_translation(repository, key)
    #         del new_file_info[key]

    return update_sources(repository, to_upload)

def update_sources(repository, new_files, all_files):
    old_file_info, file_info = crowdin_upload_sources(repository, new_files)

    update_files = set(new_files)

    for crowdin_file_name, metadata in [(key, value) for key, value in file_info.items() if key.find(repository.crowdin.single_folder) == 0 and 'id' in value]:
        if metadata['translated'] == metadata['phrases']:
            continue

        file = get_local_file(repository, crowdin_file_name)

        target_file = 'ja/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/ja/')

        if os.path.isfile(target_file):
            os.remove(target_file)

        update_files.add(file)

    if repository.crowdin.delete_enabled:
        file_info = pre_translate(repository, update_files, file_info)
    else:
        for file in update_files:
            delete_code_translations(repository, file, file_info)

        file_info = get_crowdin_file_info(repository)

    crowdin_download_translations(repository, all_files, file_info)

    return old_file_info, file_info

# Retrieve the list of all files we should translate and all updated files that
# we need to re-translate.

def get_branch_files(repository, check_upstream=False):
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

    new_files = get_eligible_files(repository, diff_output, 'en')

    lstree_output = git.ls_tree('-r', '--name-only', repository.github.branch, strip=False)
    all_files = get_eligible_files(repository, lstree_output, 'en')

    return new_files, all_files

# Update local copies of translations, translation memory, and glossaries.

def get_repository_state(repository, refresh_paths=None, check_upstream=False):
    global git_root
    git_root = repository.github.git_root
    
    logging.info('cd %s' % git_root)
    os.chdir(git_root)

    if refresh_paths is None:
        new_files, all_files = get_branch_files(repository, check_upstream)
    else:
        new_files = refresh_paths
        _, all_files = get_branch_files(repository, check_upstream)

    file_info = get_crowdin_file_info(repository)

    return new_files, all_files, file_info

def check_file_lists(repository, new_files, all_files):
    for file in all_files:
        if not os.path.exists(file):
            continue

        with open(file, 'r') as f:
            file_content = f.read()

        if re.search('@[^@ ]*-[^@ ]*@', file_content) is None:
            continue

        target_file = 'ja/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/ja/')

        if not os.path.exists(target_file):
            continue

        with open(target_file, 'r') as f:
            file_content = f.read()

        if file_content.find('@<') == -1 and file_content.find('>@') == -1:
            continue

        os.remove(target_file)
        
        if file not in new_files:
            new_files.append(file)

    for file in new_files:
        target_file = 'ja/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/ja/')

        if os.path.isfile(target_file):
            os.remove(target_file)

    for file in set(all_files) - set(new_files):
        target_file = 'ja/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/ja/')

        if not os.path.isfile(target_file):
            new_files.append(file)

def update_repository(repository, refresh_paths=None, check_upstream=False, create_issues=False):
    step_number = 1

    logging.info('step %d: get repository state for translation download' % step_number)
    step_number = step_number + 1

    new_files, all_files, file_info = get_repository_state(repository, refresh_paths, check_upstream)

    logging.info('step %d: check for existing translations of %d files' % (step_number, len(all_files)))
    step_number = step_number + 1

    check_file_lists(repository, new_files, all_files)

    logging.info('step %d: add %d source files to crowdin' % (step_number, len(new_files)))

    old_file_info, file_info = update_sources(repository, new_files, all_files)

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

    logging.info('step %d: download translation memory and glossary' % step_number)
    step_number = step_number + 1

    save_translation_memory(repository)
    save_glossary(repository)

    logging.info('cd -')
    os.chdir(initial_dir)
    
    return new_files, all_files, file_info