import React from 'react';
import ReactDOM from "react-dom";

// Simple test component
function TestApp() {
  return (
    <div style={{padding: '20px'}}>
      <h1>Test React App</h1>
      <p>If you see this, React is working!</p>
      <p>Server should be at: http://10.0.0.1:8000</p>
    </div>
  );
}

ReactDOM.render(
  <React.StrictMode>
    <TestApp />
  </React.StrictMode>,
  document.getElementById('root')
);
