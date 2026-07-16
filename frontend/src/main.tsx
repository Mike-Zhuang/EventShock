import React from 'react';
import ReactDOM from 'react-dom/client';
import '@carbon/styles/css/styles.css';
import './styles.css';
import { App } from './app';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
