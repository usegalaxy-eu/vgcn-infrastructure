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

    stage('Deploy') {
      when {
        branch 'master'
      }

      environment {
        OS_AUTH_URL = "asdf"
        OS_PASSWORD = "asdf"
        OS_PROJECT_NAME = "asdf"
        OS_REGION_NAME = "asdf"
        OS_TENANT_ID = "asdf"
        OS_TENANT_NAME = "asdf"
        OS_USERNAME = "asdf"
      }

      steps {
        sh 'pip install -r requirements.txt'
        sh 'python ensure-enough.py'
      }
    }
  }
}
