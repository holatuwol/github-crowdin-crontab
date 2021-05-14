from crowdin_sync import update_repository
from disclaimer import add_disclaimer_learn
from file_manager import get_eligible_files
import git
import os

def add_disclaimers_to_learn(repository, language):
    old_dir = os.getcwd()

    os.chdir(repository.github.git_root)

    lstree_output = git.ls_tree('-r', '--name-only', repository.github.branch, strip=False)
    all_files = get_eligible_files(repository, lstree_output, 'en')

    for file in all_files:
        if file[file.rfind('.')+1:] == 'html':
            continue

        target_file = language + '/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/%s/' % language)

        if not os.path.exists(target_file):
            continue

        new_title, old_content, new_content = add_disclaimer_learn(target_file, language)

        if old_content != new_content:
            with open(target_file, 'w') as f:
                f.write(new_title)
                f.write('\n')
                f.write(new_content)

    os.chdir(old_dir)

def copy_learn_to_crowdin(repository, language):
    update_repository(repository, sync_sources=True)

def copy_crowdin_to_learn(repository, language):
    update_repository(repository, sync_sources=False)

    # add_disclaimers_to_learn(repository, language)