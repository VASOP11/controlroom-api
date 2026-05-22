import React, { useEffect, useState } from 'react';
import axios from 'axios';

const Dashboard = () => {
    const [leads, setLeads] = useState([]);

    useEffect(() => {
        const fetchLeads = async () => {
            const response = await axios.get('/api/leads');
            setLeads(response.data);
        };
        fetchLeads();
    }, []);

    return (
        <div>
            <h1>Lead Dashboard</h1>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Primary Identifier</th>
                        <th>Score</th>
                        <th>Tier</th>
                    </tr>
                </thead>
                <tbody>
                    {leads.map(lead => (
                        <tr key={lead.id}>
                            <td>{lead.id}</td>
                            <td>{lead.primary_identifier}</td>
                            <td>{lead.score}</td>
                            <td>{lead.tier}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
};

export default Dashboard;