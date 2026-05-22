import React, { useState } from 'react';
import axios from 'axios';

const AddLeadForm = () => {
    const [leadData, setLeadData] = useState({
        lead_id: '',
        primary_identifier: '',
        org_id: '',
        // add more fields as necessary
    });

    const handleChange = e => {
        setLeadData({ ...leadData, [e.target.name]: e.target.value });
    };

    const handleSubmit = async e => {
        e.preventDefault();
        await axios.post('/api/leads', leadData);
        // Clear form or show success message
    };

    return (
        <form onSubmit={handleSubmit}>
            <div>
                <label>Lead ID:</label>
                <input name="lead_id" value={leadData.lead_id} onChange={handleChange} required />
            </div>
            <div>
                <label>Primary Identifier:</label>
                <input name="primary_identifier" value={leadData.primary_identifier} onChange={handleChange} required />
            </div>
            <div>
                <label>Organization ID:</label>
                <input name="org_id" type="number" value={leadData.org_id} onChange={handleChange} required />
            </div>
            <button type="submit">Add Lead</button>
        </form>
    );
};

export default AddLeadForm;