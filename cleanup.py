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