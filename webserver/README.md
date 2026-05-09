# RVSecurity

## Setup Dev Environment
- move to location where you want the clone to exist
- `git clone git@github.com:joram/RVSecurity.git`


Now you have a folder of code called `RVSecurity`

## Want to Commit to Cloud Changes
- `git status` to list the changed files (in red)
- `git add .` to stage them all
- `git status` will list all staged changes (all in green)
- `git commit -m "<descriptive message>"` to create a commit
- `git push origin main` Push all commits into Cloud main

## Want to pull down changes
- `git pull origin main'  Brings down all Cloud main cahnges

## React Client and Server commands
- app/App.jsx file contains most of the React client code (Loads svg file and maps variables)
- api/server.py contains the server code (must write/update all the variables)
- to rebuild compiled version of the app: 'make build'
- to start the server (assuming make works) `make start_server` Then open browswer to localhost:8000
- to start the app (assuming make works) `make start_client`
- after develeopment loop when ready to deploy: 'make build' (don't foget to commit to cloud)
- Webpage location:  http://localhost:3000
- api documentation page: http://localhost:8000/docs
- Fast debug/test loop steps:
  - In seperate cmd window: make start_server
  - In IDE cmd window: make start_client  (this will slowly bring up a browser window)
  - Then each time you do an IDE save on the client code, it will automatically rebuild and be usable on the browser with a refresh


## Terminology
- Server aka API - code that runs on the webpage server
- Application - web code that runs on the persons computer hitting the web page 
- REACT is the web framework; see https://reactjs.org/ (start here)
- React Sematic UI: https://react.semantic-ui.com/
- Client code: sometimes also called API code; runs on the web browser of the user
- Server code: sometimes also called Application code; runs on the machine that serves up the web pages


