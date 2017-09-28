pipeline {
	agent {
		docker {
			image 'python:3.6'
			args '-u root'
		}
	}

	stages {
		stage('Linting') {
			steps {
				sh 'pip install pyyaml pykwalify'
				sh 'pykwalify -d resources.yaml -s schema.yaml'
			}
		}

		stage('Testing') {
			steps {
				sh 'pip install -r requirements.txt nose'
				sh 'nosetests tests.py -s'
			}
		}

		stage('Deploy') {
			when {
				branch 'master'
			}

			steps {
				sh 'pip install -r requirements.txt'

				withCredentials([
					string(credentialsId: 'OS_AUTH_URL', variable: 'OS_AUTH_URL'),
					string(credentialsId: 'OS_PASSWORD', variable: 'OS_PASSWORD'),
					string(credentialsId: 'OS_PROJECT_NAME', variable: 'OS_PROJECT_NAME'),
					string(credentialsId: 'OS_REGION_NAME', variable: 'OS_REGION_NAME'),
					string(credentialsId: 'OS_TENANT_ID', variable: 'OS_TENANT_ID'),
					string(credentialsId: 'OS_TENANT_NAME', variable: 'OS_TENANT_NAME'),
					string(credentialsId: 'OS_USERNAME', variable: 'OS_USERNAME'),
				]) {
						sh 'python ensure-enough.py'
				}
			}
		}
	}
}
