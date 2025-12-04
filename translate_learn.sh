#!/bin/bash

learn_domain='learn-uat-preprod.lxc.liferay.com.localhost:8088'
# learn_domain='learn-uat.liferay.com'
# learn_domain='learn.liferay.com'

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

learn_domain="${learn_domain}" \
learn_group_id="${learn_group_id}" \
learn_scratch_dir="${learn_scratch_dir}" \
client_id="${client_id}" \
client_secret="${client_secret}" \
  python -u translate_learn.py $@ 2>&1 | tee translate_learn.log