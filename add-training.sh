#!/bin/bash

export LC_NUMERIC="en_US.UTF-8"

if ([ $# -lt 5 ]); then
    echo "Usage:"
    echo
    echo "  $0 <training-identifier> <vm-size (e.g. c1.c28m225d50)> <vm-count> <start in YYYY-mm-dd> <end in YYYY-mm-dd> [--donotautocommitpush]"
    echo
    exit 1;
fi

training_identifier=$(echo "$1" | tr '[:upper:]' '[:lower:]')
vm_size=${2:-c.c10m55}
vm_count=${3:-1}
start=$4
end=$5
autopush=1
if [[ "$6" == "--donotautocommitpush" ]]; then
	autopush=0
fi

short=$(echo "$training_identifier" | cut -c1-4)

output="instance_training-${training_identifier}.tf"

cat >> resources.yaml <<-EOF
  training-${short}:
    count: ${vm_count}
    flavor: ${vm_size}
    start: ${start}
    end: ${end}
    group: training-${training_identifier}
EOF

if (( autopush == 1 )); then
	git add resources.yaml
	git commit -m 'New training'
	git push
fi

vm_cpu=$(echo $vm_size | sed 's/[^0-9]/ /g' | awk '{print $2}')
vm_mem=$(echo $vm_size | sed 's/[^0-9]/ /g' | awk '{print $3}')

ts_end=$(date -d "$end 23:59" +%s)
ts_stt=$(date -d "$start 00:00" +%s)
vm_seconds=$(( ts_end - ts_stt ))
price=$(python3 cost.py $vm_cpu $vm_mem $vm_seconds | head -n 1)
machines=$(python3 cost.py $vm_cpu $vm_mem $vm_seconds | tail -n 1)
aws_id=$(echo $machines | sed "s/'/\"/g" | jq .name -r)
price=$(echo "$price * $vm_count" | bc -l)
price_int=$(printf "%0.2f" $price)
yourname=$(git config --global --get user.name)

printf "
Subject: UseGalaxy.eu TIaaS Request: Approved

Dear **X**,

Thanks for submitting your TIaaS request! Based on your choice, we have allocated ${vm_count} servers, each with ${vm_cpu} cores and ${vm_mem} GB of RAM. If you find that it is not enough for your training, please contact us and we can update that at any time.

TIaaS provides a private queue for your training in addition to the regular one, which should make your jobs run a bit faster. To make use of it, we have created a training group for you that is accessible at

https://usegalaxy.eu/join-training/${training_identifier}

Please ask your users to go to that URL during your training (from ${start} to ${end}). Once it is over, the link will not be usable anymore but the users can still access their data at usegalaxy.eu.

Queue Status:
If you find yourself wondering where your students are during the training, you can use the queue status page to see which jobs are being run by people in your training: https://usegalaxy.eu/join-training/${training_identifier}/status

Storage:
We recommend to use Galaxy's short-term storage during the training. This will help us in cleaning up unused data and offer Galaxy as a more sustainable service. For more information please consult our [storage page](https://galaxyproject.org/eu/storage/).

Support:
If during the workshop you experience issues with the server, you can ask for support in the Galaxy Europe Gitter channel: https://matrix.to/#/#usegalaxy-eu_Lobby:gitter.im
or via email: galaxy-ops@informatik.uni-freiburg.de


Please keep in mind that usegalaxy.eu is a free service and we do not charge any fees to our users. We do our best to maintain a highly available and reliable cluster, but there may still be outages we cannot control. We would like to ask you to be lenient in such cases.
You can view our service status here: https://status.galaxyproject.org/

In case of prolonged unexpected server outage, you could consider using one of the other usegalaxy.* instances. You can find them on the status page mentioned above. Keep in mind that your registered TIaaS session with the dashboard and separate queue is only available on usegalaxy.eu.

AWS Estimate:
If you wanted to run a similar training on AWS, we estimate that for ${vm_count} ${aws_id}machine(s), it would cost ${price_int} USD.

Workshop Feedback:
When your workshop is over, if you used GTN materials, please let us know how it went on the workshop feedback issue: https://github.com/galaxyproject/training-material/issues/1452

TIaaS Feedback:
We encourage you to send us a short review sharing your experience, tips for other instructors,... that we will publish in https://galaxyproject.eu/news?tag=TIaaS. Your feedback is very valuable to keep this service up and running for free.

We really appreciate your support. Thank you very much for using Galaxy and don't hesitate to contact us if you have any questions!

Kind regards,

${yourname}

--
UseGalaxy.eu
Bioinformatics Group
Department of Computer Science
Albert-Ludwigs-University Freiburg
Georges-Köhler-Allee 106
79110 Freiburg, Germany
"
