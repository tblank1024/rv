import React from 'react';
import ReactDOM from "react-dom";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./pages/Layout";
import Home from "./page-home/Home";
import Contact from "./pages/Contact";
import NoPage from "./pages/NoPage";
import Power from "./page-power/Power";
import reportWebVitals from './reportWebVitals';
import 'semantic-ui-css/semantic.min.css';
import './index.css';
import {IPADDR, PORT} from './constants';


console.log(IPADDR, PORT)

export default function App() {
  return (
    <div className="body">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="/index.html" element={<Home />} />
            <Route path="contact" element={<Contact />} />
            <Route path="power" element={<Power />}/>
            <Route path="*" element={<NoPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </div>
  );
}

ReactDOM.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
  document.getElementById('root')
);

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();

/*
const root = ReactDOM.createRoot(document.getElementById('root'));

root.render(<App />); 

reportWebVitals();
*/
