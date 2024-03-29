import os

def get_folders(files):
    return sorted(set([os.path.dirname(file) if os.path.isfile(file) else file for file in files]))

# We need to be able to convert a list of files into a list of root folders,
# since we want to break everything up at the root folder level.

def get_root_folders(repository, candidate_files):
    if repository.github.single_folder is None:
        base_folder = repository.github.project_folder
    else:
        base_folder = repository.github.single_folder

    prefix = base_folder + '/'

    matching_folders = [
        folder for folder in get_folders(candidate_files)
            if folder.find(prefix) == 0 or folder == base_folder
    ]

    root_folders = []

    for matching_folder in matching_folders:
        if len(root_folders) == 0 or matching_folder.find(root_folders[-1]) != 0:
            root_folders.append(matching_folder)

    return root_folders

def get_crowdin_file(repository, local_file):
    if local_file.find(repository.github.project_folder) == 0:
        return repository.crowdin.dest_folder + '/' + local_file[len(repository.github.project_folder)+1:]

    return None

def get_local_file(repository, crowdin_file):
    if crowdin_file.find(repository.crowdin.dest_folder) == 0:
        return repository.github.project_folder + crowdin_file[len(repository.crowdin.dest_folder):]

    return None

def get_files(folder):
    files = []

    for name in os.listdir(folder):
        path = '%s/%s' % (folder, name)

        if os.path.isdir(path):
            files.extend(get_files(path))
        else:
            files.append(path)

    return list(files)

def get_translation_path(file, source_language, target_language):
    source_language_path = source_language

    if source_language.find('-') != -1:
        source_language_path = source_language[:source_language.find('-')]

    target_language_path = target_language

    if target_language.find('-') != -1:
        target_language_path = target_language[:target_language.find('-')]

    if file[0:3] == '%s/' % source_language_path:
        return '%s/%s' % (target_language_path, file[3:])
    else:
        return file.replace('/%s/' % source_language_path, '/%s/' % target_language_path)

def is_translation_eligible(repository, file, language_id):
    if repository.github.single_folder is None:
        prefix = repository.github.project_folder + '/'
    else:
        prefix = repository.github.single_folder + '/'

    prefix = language_id + '/' + prefix[3:] if prefix[0:3] == 'en/' else prefix.replace('/en/', '/%s/' % language_id)

    if file.find(prefix) == 0:
        if file[0:3] == language_id + '/' or file.find('/' + language_id + '/') != -1:
            if file[-9:] == '.markdown' or file[-3:] == '.md' or file[-5:] == '.html' or file[-4:] == '.rst':
                return True

    return False

def get_eligible_files(repository, output, language_id):
    return [
        file for file in output.split('\n')
            if is_translation_eligible(repository, file, language_id)
    ]