import React from 'react';
import ReactDOM from "react-dom";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import 'semantic-ui-css/semantic.min.css';
import './index.css';
import {IPADDR, PORT} from './constants';

// Import components with error handling
let Layout, Home, PlexSvr, Internet, NoPage, Power, Debug;

try {
  Layout = require("./pages/Layout").default;
  Home = require("./page-home/Home").default;
  PlexSvr = require("./page-Plex-Svr/PlexSvr").default;
  Internet = require("./page-internet/Internet").default;
  NoPage = require("./pages/NoPage").default;
  Power = require("./page-power/Power").default;
  Debug = require("./page-debug/debug").default;
} catch (error) {
  console.error("Error importing components:", error);
}

console.log("Constants:", IPADDR, PORT)
console.log("Components loaded:", {Layout, Home, PlexSvr, Internet, NoPage, Power, Debug});

export default function App() {
  return (
    <div className="body">
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/" element={Layout ? <Layout /> : <div>Layout not loaded</div>}>
            <Route index element={Home ? <Home /> : <div>Home not loaded</div>} />
            <Route path="/index.html" element={Home ? <Home /> : <div>Home not loaded</div>} />
            <Route path="wifi" element={PlexSvr ? <PlexSvr /> : <div>PlexSvr not loaded</div>} />
            <Route path="internet" element={Internet ? <Internet /> : <div>Internet not loaded</div>} />
            <Route path="power" element={Power ? <Power /> : <div>Power not loaded</div>}/>
            <Route path="debug" element={Debug ? <Debug /> : <div>Debug not loaded</div>}/>
            <Route path="*" element={NoPage ? <NoPage /> : <div>NoPage not loaded</div>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </div>
  );
}

try {
  ReactDOM.render(
    <App />,
    document.getElementById('root')
  );
  console.log("App rendered successfully");
} catch (error) {
  console.error("Error rendering app:", error);
  // Fallback rendering
  ReactDOM.render(
    <div style={{padding: '20px'}}>
      <h1>Error Loading App</h1>
      <p>Check console for details</p>
      <pre>{error.toString()}</pre>
    </div>,
    document.getElementById('root')
  );
}
