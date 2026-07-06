#!/bin/bash

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

if [ "${learn_domain}" == "learn.liferay.com" ]; then
	learn_group_id='23484947'
	client_id="$(op item get "Liferay Learn Japan OAuth2 PRD" --fields "Client ID")"
	client_secret="$(op item get "Liferay Learn Japan OAuth2 PRD" --fields "Client Secret")"
	learn_scratch_dir="/home/me/dev/translate-learn/${learn_domain}"
else
	learn_group_id='32483059'
	client_id="$(op item get "OAuth2 learn-uat.liferay.com" --fields username)"
	client_secret="$(op item get "OAuth2 learn-uat.liferay.com" --fields credential --reveal)"
	learn_scratch_dir="/home/me/dev/translate-learn/learn-uat.liferay.com"
fi

ACTION=$(
	echo "check_outdated_articles
copy_learn_to_local
copy_local_to_crowdin
translate_learn_on_crowdin
copy_crowdin_to_local
copy_local_to_learn" | fzf --query="${1}" --select-1
)

if [ "" != "${ACTION}" ]; then
	learn_domain="${learn_domain}" \
	learn_group_id="${learn_group_id}" \
	learn_scratch_dir="${learn_scratch_dir}" \
	client_id="${client_id}" \
	client_secret="${client_secret}" \
		uv run translate_learn.py "${ACTION}" 2>&1 | tee translate_learn.log
fi