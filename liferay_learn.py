from crowdin_sync import update_repository
from disclaimer import add_disclaimer_learn
import os

def copy_learn_to_crowdin(repository, language):
    update_repository(repository, sync_sources=True)

def copy_crowdin_to_learn(repository, language):
    new_files, all_files, file_info = update_repository(repository, sync_sources=False)

    old_dir = os.getcwd()

    os.chdir(repository.github.git_root)

    for file in all_files:
        target_file = language + '/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/%s/' % language)
        new_title, old_content, new_content = add_disclaimer_learn(target_file, language)

        if old_content != new_content:
            with open(target_file, 'w') as f:
                f.write(new_title)
                f.write('\n')
                f.write(new_content)

    os.chdir(old_dir)
