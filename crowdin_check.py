#!/usr/bin/env python

from crowdin_util import CrowdInRepository, crowdin_request, get_crowdin_file_info
import logging
import sys

from session import save_session

logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)

valid_tag_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ:_-"


# Clear out code translations


def check_pre_translations(
    project_id,
    project_name,
    project_folder,
    source_language,
    target_language,
    force=False,
):
    repository = CrowdInRepository(
        None,
        None,
        source_language,
        project_id,
        project_name,
        None,
        project_folder,
        False,
        False,
    )

    file_info = get_crowdin_file_info(repository, target_language)

    for file_name, file_metadata in file_info.items():
        api_path = "/projects/%s/languages/%s/translations" % (
            repository.project_id,
            target_language,
        )

        pagination_data = {"fileId": file_metadata["id"], "offset": 0, "limit": 500}

        status_code, response_data = crowdin_request(api_path, "GET", pagination_data)

        for item in response_data:
            if is_malformed_translation(item["data"]["text"]):
                print(
                    "https://crowdin.com/translate/liferay-japan-documentation/%s/en-%s#%s"
                    % (file_metadata["id"], target_language, item["data"]["stringId"])
                )
                print(item["data"]["text"])
                print()


def hide_code_translations(
    repository, source_language, target_language, file_name, file_metadata
):
    logging.info("Checking auto code translations for file %s" % file_name)

    project_id = repository.project_id
    file_id = file_metadata["id"]

    status_code, response_data = crowdin_request(
        "/projects/%s/strings" % project_id, "GET", {"fileId": file_id}
    )

    for entry in response_data:
        is_hide_translation = (
            entry["data"]["context"].find("/pre") != -1
            or entry["data"]["context"].find("/code") != -1
        )
        was_hidden_translation = entry["data"]["isHidden"]
        string_id = entry["data"]["id"]

        if is_hide_translation == was_hidden_translation:
            continue

        if is_hide_translation:
            set_translation_hidden(repository, project_id, string_id, True)
        else:
            set_translation_hidden(repository, project_id, string_id, False)

    return False


def is_malformed_translation(text):
    open_tags = []

    i = 0
    max_i = len(text)

    while i < max_i:
        if text[i] != "<":
            i = i + 1
            continue

        if text[i + 1] == "/":
            if len(open_tags) == 0:
                return True

            j = i + 2

            while j < max_i:
                if text[j] in valid_tag_chars:
                    j = j + 1
                    continue

                tag_name = text[i + 2 : j]
                if tag_name != open_tags[-1]:
                    return True

                open_tags.pop()
                break

            i = j + 1
        else:
            j = i + 1

            while j < max_i:
                if text[j] in valid_tag_chars:
                    j = j + 1
                    continue

                tag_name = text[i + 1 : j]
                open_tags.append(tag_name)
                break

            i = j + 1

    return False


def process_code_translations(
    project_id,
    project_name,
    project_folder,
    source_language,
    target_language,
    force=False,
):
    repository = CrowdInRepository(
        None,
        None,
        source_language,
        project_id,
        project_name,
        None,
        project_folder,
        False,
        False,
    )

    file_info = get_crowdin_file_info(repository, target_language)

    for file_name, file_metadata in file_info.items():
        if (
            force
            or "id" in file_metadata
            and file_metadata["phrases"] != file_metadata["translated"]
        ):
            hide_code_translations(
                repository, source_language, target_language, file_name, file_metadata
            )


def set_translation_hidden(repository, project_id, string_id, is_hidden):
    crowdin_request(
        "/projects/%s/strings/%s" % (project_id, string_id),
        "PATCH",
        [{"op": "replace", "path": "/isHidden", "value": is_hidden}],
    )


if __name__ == "__main__":
    try:
        check_pre_translations(*sys.argv[1:])
        process_code_translations(*sys.argv[1:])
    finally:
        save_session()
