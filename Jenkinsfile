pipeline {
  agent {
    docker {
      image 'python:3.6'
      args '-u root'
    }
  }

  environment {
    OS_AUTH_URL = credentials('OS_AUTH_URL')
    OS_PASSWORD = credentials('OS_PASSWORD')
    OS_PROJECT_NAME = credentials('OS_PROJECT_NAME')
    OS_REGION_NAME = credentials('OS_REGION_NAME ')
    OS_TENANT_ID = credentials('OS_TENANT_ID')
    OS_TENANT_NAME = credentials('OS_TENANT_NAME')
    OS_USERNAME = credentials('OS_USERNAME')
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

      steps {
        sh 'pip install -r requirements.txt'
        sh 'python ensure-enough.py'
      }
    }
  }
}
