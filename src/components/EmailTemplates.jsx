import React, { useEffect, useState } from 'react';
import axios from 'axios';

const EmailTemplates = () => {
    const [templates, setTemplates] = useState([]);

    useEffect(() => {
        const fetchTemplates = async () => {
            const response = await axios.get('/api/email/templates');
            setTemplates(response.data);
        };
        fetchTemplates();
    }, []);

    return (
        <div>
            <h2>Email Templates</h2>
            <ul>
                {templates.map(template => (
                    <li key={template.id}>{template.name}: {template.subject}</li>
                ))}
            </ul>
        </div>
    );
};

export default EmailTemplates;