from crowdin_check import hide_code_translations
from crowdin_util import (
    crowdin_request,
    get_crowdin_file_info,
    get_directory,
    get_repository_state,
    upload_file_to_crowdin_storage,
)
from datetime import datetime, timedelta
import logging
import os
import requests
import time
from zipfile import ZipFile

# Wrapper functions to upload sources and download translations.


def crowdin_download_translations(
    repository, source_language, target_language, refresh_files, file_info
):
    source_language = source_language[:2]
    target_language = target_language[:2]

    updated_files = list(refresh_files)

    api_path = "/projects/%s/directories" % repository.project_id

    status_code, response_data = crowdin_request(api_path, "GET", {})

    dest_directories = [
        directory["data"]
        for directory in response_data
        if directory["data"]["name"] == repository.dest_folder
    ]

    if len(dest_directories) != 1:
        logging.info("Unable to find data directory %s" % repository.dest_folder)
        return

    dest_directory_id = dest_directories[0]["id"]

    def get_recent_build(build_id):
        if build_id is not None:
            api_path = "/projects/%s/translations/builds/%s" % (
                repository.project_id,
                build_id,
            )

            status_code, response_data = crowdin_request(api_path, "GET", {})

            if status_code == 200:
                build_id = response_data["id"]

                return response_data

        api_path = "/projects/%s/translations/builds" % repository.project_id

        logging.info("Retrieving build list...")
        status_code, response_data = crowdin_request(api_path, "GET", {})

        for build in response_data:
            if (
                "directoryId" not in build["data"]
                or build["data"]["directoryId"] != dest_directory_id
            ):
                continue

            created_at = build["data"]["createdAt"]

            check_time = datetime.strptime(
                created_at[:-3] + created_at[-2:], "%Y-%m-%dT%H:%M:%S%z"
            )
            min_time = datetime.now(check_time.tzinfo) - timedelta(minutes=30)

            if check_time > min_time:
                return build["data"]

        return None

    recent_build = get_recent_build(None)

    if recent_build is None:
        api_path = "/projects/%s/translations/builds/directories/%s" % (
            repository.project_id,
            dest_directory_id,
        )

        data = {"targetLanguageIds": [source_language, target_language]}

        status_code, response_data = crowdin_request(api_path, "POST", data)
        recent_build = response_data

    while recent_build["status"] != "finished":
        logging.info("Waiting for build to finish...")
        time.sleep(15)
        recent_build = get_recent_build(recent_build["id"])

    api_path = "/projects/%s/translations/builds/%s/download" % (
        repository.project_id,
        recent_build["id"],
    )

    status_code, response_data = crowdin_request(api_path, "GET", {})

    r = requests.get(response_data["url"])

    export_file_name = "export-%f.zip" % datetime.utcnow().timestamp()

    logging.info(
        "Downloading build from %s to %s" % (response_data["url"], export_file_name)
    )

    with open(export_file_name, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    return extract_crowdin_translation(
        repository, export_file_name, source_language, target_language
    )


def crowdin_upload_sources(repository, source_language, target_language, new_files):
    if source_language.find("-") != -1:
        source_language = source_language[: source_language.find("-")]

    if target_language.find("-") != -1:
        target_language = target_language[: target_language.find("-")]

    before_upload = get_crowdin_file_info(repository, target_language)

    existing_files = {}

    for i, file in enumerate(new_files):
        file_name = os.path.basename(file)

        logging.info("Preparing to upload file %d/%d..." % (i, len(new_files)))

        directory = get_directory(repository, os.path.dirname(file))
        directory_id = directory["id"]

        logging.info("Uploading file %d/%d (%s)..." % (i, len(new_files), file))

        status_code, response_data = upload_file_to_crowdin_storage(file)

        if directory_id not in existing_files:
            data = {"directoryId": directory_id}

            api_path = "/projects/%s/files" % repository.project_id
            status_code, directory_response_data = crowdin_request(
                api_path, "GET", data
            )
            existing_files[directory_id] = directory_response_data

        matching_files = [
            directory_file
            for directory_file in existing_files[directory_id]
            if directory_file["data"]["name"] == file_name
        ]

        data = {"storageId": response_data["id"]}

        logging.info(
            "Telling crowdin about uploaded file %d/%d (%s)..."
            % (i, len(new_files), file_name)
        )

        if len(matching_files) == 1:
            data["updateOption"] = "keep_translations_and_approvals"
            file_id = matching_files[0]["data"]["id"]
            api_path = "/projects/%s/files/%s" % (repository.project_id, file_id)
            crowdin_request(api_path, "PUT", data)
        else:
            data["name"] = file_name
            data["directoryId"] = directory_id
            api_path = "/projects/%s/files" % repository.project_id
            crowdin_request(api_path, "POST", data)

    if len(new_files) > 0:
        after_upload = get_crowdin_file_info(repository, target_language)
    else:
        after_upload = before_upload

    return before_upload, after_upload


def extract_crowdin_translation(
    repository, export_file_name, source_language, target_language
):
    if export_file_name is None:
        return None

    source_file_prefix = "%s/" % (source_language)
    target_file_prefix = "%s/" % (target_language)

    if not os.path.exists(export_file_name):
        return

    target_folder = os.path.join(repository.git_root, repository.dest_folder)

    with ZipFile(export_file_name) as zipdata:
        for zipinfo in zipdata.infolist():
            if zipinfo.is_dir():
                os.makedirs(zipinfo.filename, exist_ok=True)
                continue

            if zipinfo.filename.find(source_file_prefix) == 0:
                with open("%s.crc32" % zipinfo.filename, "w", encoding="utf-8") as f:
                    f.write(str(zipinfo.CRC))

            if zipinfo.filename.find(target_file_prefix) == 0:
                zipdata.extract(zipinfo, target_folder)

    return export_file_name


def get_missing_phrases_file_ids(repository, source_language, target_language):
    _, file_info = get_repository_state(repository, target_language)

    missing_phrases_files = {}

    for crowdin_file, metadata in file_info.items():
        if metadata["phrases"] != metadata["translated"]:
            missing_phrases_files[metadata["id"]] = crowdin_file

    return missing_phrases_files


def pre_translate(repository, source_language, target_language):
    _, file_info = get_repository_state(repository, target_language)

    for crowdin_file, metadata in file_info.items():
        if metadata["phrases"] != metadata["translated"]:
            hide_code_translations(
                repository, source_language, target_language, crowdin_file, metadata
            )

    translate_with_machine(
        repository, source_language, target_language, "translation memory"
    )

    # if source_language in ["en", "ja"] and target_language in ["en", "ja"]:
    #     translate_with_machine(repository, source_language, target_language, "DeepL")

    translate_with_machine(repository, source_language, target_language, "Google")


engines = {"DeepL": 245660, "Google": 213743, "translation memory": "tm"}


def translate_with_machine(repository, source_language, target_language, engine_name):
    file_ids = get_missing_phrases_file_ids(
        repository, source_language, target_language
    )

    file_count = len(file_ids)

    logging.info(f"{file_count} files need to be updated using {engine_name}")

    if file_count == 0:
        return

    engine = engines[engine_name]

    update_api_path = "/projects/%s/pre-translations" % repository.project_id

    for i, file_id in enumerate(file_ids.keys()):
        logging.info(
            "crowdin-api pre-translate %s (%d/%d)" % (engine, i + 1, file_count)
        )
        logging.info(file_ids[file_id])

        data = {
            "languageIds": [target_language],
            "method": "tm" if engine == "tm" else "mt",
            "autoApproveOption": "perfectMatchOnly",
            "fileIds": [file_id],
        }

        if engine != "tm":
            data["engineId"] = engine

        status_code, response_data = crowdin_request(update_api_path, "POST", data)

        status_api_path = "/projects/%s/pre-translations/%s" % (
            repository.project_id,
            response_data["identifier"],
        )

        while response_data["finishedAt"] is None:
            logging.info(
                f"Waiting for {engine_name} {i+1}/{file_count} to finish..."
            )
            time.sleep(5)
            status_code, response_data = crowdin_request(status_api_path, "GET", {})
