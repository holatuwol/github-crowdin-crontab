#!/bin/bash

SCRIPT_FOLDER=$(dirname $0)
source ${SCRIPT_FOLDER}/bin/activate

if [ -z "${S3_BUCKET}" ]; then
	S3_BUCKET=mdang.tokyo
fi

if [ -z "${AWS_PROFILE}" ]; then
	AWS_PROFILE=default
fi

# learn_domain='learn-uat-preprod.lxc.liferay.com.localhost:8088'
# learn_domain='learn-uat.liferay.com'
learn_domain='learn.liferay.com'

op() {
	if [ -f /usr/bin/op ]; then
		OP_BINARY='/usr/bin/op'
	elif [ "" != "${WINDOWS_HOME}" ]; then
		OP_BINARY="$(find "${WINDOWS_HOME}/AppData/Local/Microsoft/WinGet/Packages/" -name op.exe)"
	fi

	if [ "" != "${OP_BINARY}" ]; then
		"${OP_BINARY}" "$@"
	else
		echo 'Unable to find 1Password CLI'
	fi
}

learn_scratch_parent_dir="/home/me/dev/translate-learn"

if [ "${learn_domain}" == "learn.liferay.com" ]; then
	learn_group_id='23484947'
	client_id="$(op item get "Liferay Learn Japan OAuth2 PRD" --fields "Client ID")"
	client_secret="$(op item get "Liferay Learn Japan OAuth2 PRD" --fields "Client Secret")"
	learn_scratch_dir="${learn_scratch_parent_dir}/learn.liferay.com"
	learn_scratch_file="learn.liferay.com.7z"
else
	learn_group_id='32483059'
	client_id="$(op item get "OAuth2 learn-uat.liferay.com" --fields username)"
	client_secret="$(op item get "OAuth2 learn-uat.liferay.com" --fields credential --reveal)"
	learn_scratch_dir="${learn_scratch_parent_dir}/learn-uat.liferay.com"
	learn_scratch_file="learn-uat.liferay.com.7z"
fi

loadbackup() {
	if [ -d "${learn_scratch_dir}" ]; then
		return 0
	fi

	mkdir -p "${learn_scratch_parent_dir}"
	aws s3 --profile ${AWS_PROFILE} cp s3://${S3_BUCKET}/translate-learn/${learn_scratch_file} "${learn_scratch_parent_dir}/${learn_scratch_file}.gz"

	pushd "${learn_scratch_parent_dir}" > /dev/null
	gunzip ${learn_scratch_file}.gz
	7z x ${learn_scratch_file}
	rm ${learn_scratch_file}
	popd > /dev/null
}

storebackup() {
	rm -f "${learn_scratch_dir}.7z.gz"

	7z a ${learn_scratch_dir}.7z ${learn_scratch_dir}

	gzip -c "${learn_scratch_dir}.7z" > "${learn_scratch_dir}.7z.gz"

	aws s3 --profile ${AWS_PROFILE} cp "${learn_scratch_dir}.7z.gz" "s3://${S3_BUCKET}/translate-learn/${learn_scratch_file}" --metadata-directive REPLACE --content-encoding gzip

	rm "${learn_scratch_dir}.7z.gz"

	rm "${learn_scratch_dir}.7z"
}

ACTION=$(
	echo "check_outdated_articles
copy_learn_to_local
copy_local_to_crowdin
translate_learn_on_crowdin
copy_crowdin_to_local
copy_local_to_learn" | fzf --query="${1}" --select-1
)

if [ "" != "${ACTION}" ]; then
	loadbackup

	learn_domain="${learn_domain}" \
	learn_group_id="${learn_group_id}" \
	learn_scratch_dir="${learn_scratch_dir}" \
	client_id="${client_id}" \
	client_secret="${client_secret}" \
		uv run translate_learn.py "${ACTION}" 2>&1 | tee translate_learn.log

	storebackup
fi