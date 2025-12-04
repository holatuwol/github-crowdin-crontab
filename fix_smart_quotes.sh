#!/bin/bash

fix_file() {
    bad_ch=${1}
    good_ch=${2}
    file=${3}

    echo ${file}

    sed -i "s/${bad_ch}/${good_ch}/g" ${file}
}

update_crc32() {
    return 0

    file=${1}

    if [ ! -f ${file}.crc32 ]; then
        return
    fi

    echo "updating crc32: ${file}"

    python -c "
import binascii
import sys
with open('${file}', 'rb') as f:
    new_crc32 = str(binascii.crc32(f.read()))
with open('${file}.crc32', 'w') as f:
    f.write(new_crc32)
"
}

for ch in ‘ ’ '&rsquo;'; do
    for origin in 'learn-uat.liferay.com' 'learn.liferay.com'; do
        for file in $(grep -rFl ${ch} /home/me/dev/translate-learn/${origin}/en/); do
            fix_file ${ch} "'" ${file}
            update_crc32 ${file}
        done

        for file in $(grep -rFl ${ch} /home/me/dev/translate-learn/${origin}/ja/); do
            fix_file ${ch} "" ${file}
            rm -f ${file}.crc32
        done
    done
done

for ch in “ ” '&ldquo;' '&rdquo'; do
    for origin in 'learn-uat.liferay.com' 'learn.liferay.com'; do
        for file in $(grep -rFl ${ch} /home/me/dev/translate-learn/${origin}/en/); do
            fix_file ${ch} '"' ${file}
            update_crc32 ${file}
        done

        for file in $(grep -rFl ${ch} /home/me/dev/translate-learn/${origin}/ja/); do
            fix_file ${ch} '' ${file}
            update_crc32 ${file}
        done
    done
done