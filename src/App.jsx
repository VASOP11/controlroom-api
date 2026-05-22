import React from 'react';
import Dashboard from './components/Dashboard';
import AddLeadForm from './components/AddLeadForm';
import EmailTemplates from './components/EmailTemplates';

const App = () => {
    return (
        <div>
            <h1>Lead Management System</h1>
            <AddLeadForm />
            <Dashboard />
            <EmailTemplates />
        </div>
    );
};

export default App;