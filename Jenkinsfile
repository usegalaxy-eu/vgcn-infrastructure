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
      steps {
        sh 'pip install -r requirements.txt'
        sh 'python ensure-enough.py'
      }
    }
  }
}
