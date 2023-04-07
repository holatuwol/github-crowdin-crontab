from crowdin import crowdin_download_translations, crowdin_upload_sources, fix_product_name_tokens, get_crowdin_file_info
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

# Retrieve the list of all files we should translate and all updated files that
# we need to re-translate.

# Update local copies of translations, translation memory, and glossaries.

def get_repository_state(repository, source_language, target_language):
    global git_root
    git_root = repository.github.git_root
    
    logging.info('cd %s' % git_root)
    os.chdir(git_root)

    file_info = get_crowdin_file_info(repository, target_language)

    all_files = [
        get_local_file(repository, crowdin_file)
            for crowdin_file, metadata in file_info.items()
                if 'id' in metadata and crowdin_file.find(repository.crowdin.dest_folder) == 0
    ]

    lstree_output = git.ls_tree('-r', '--name-only', repository.github.branch, strip=False)
    branch_files = get_eligible_files(repository, lstree_output, source_language)

    all_files.extend(branch_files)

    all_files = sorted(set(all_files))

    return all_files, all_files, file_info

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

def update_repository(repository, source_language, target_language):
    step_number = 1

    logging.info('step %d: get repository state for translation download' % step_number)
    step_number = step_number + 1

    new_files, all_files, file_info = get_repository_state(repository, source_language, target_language)

    logging.info('step %d: check for existing translations of %d files' % (step_number, len(all_files)))
    step_number = step_number + 1

    check_file_lists(repository, source_language, target_language, new_files, all_files)

    if sync_sources:
        logging.info('step %d: add %d source files to crowdin' % (step_number, len(new_files)))
        step_number = step_number + 1

        old_file_info, file_info = crowdin_upload_sources(repository, source_language, target_language, new_files)

    logging.info('step %d: check for translations of %d source files' % (step_number, len(new_files)))
    step_number = step_number + 1

    crowdin_download_translations(repository, source_language, target_language, all_files, file_info)

    logging.info('cd -')
    os.chdir(initial_dir)
    
    return new_files, all_files, file_info