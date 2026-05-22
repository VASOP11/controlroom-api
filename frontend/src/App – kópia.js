import React, { useState, useEffect } from 'react';
import axios from 'axios';

function App() {
  const [leads, setLeads] = useState([]);
  const [newLead, setNewLead] = useState({ primary_identifier: '', vertical: '' });
  const [selectedLead, setSelectedLead] = useState(null);
  const [emailDraft, setEmailDraft] = useState(null);
  const [adjustment, setAdjustment] = useState(0);

  useEffect(() => {
    fetchLeads();
  }, []);

  const fetchLeads = async () => {
    try {
      const res = await axios.get('/api/leads', { headers: { Authorization: 'Bearer test-token' } });
      setLeads(res.data);
    } catch (err) {
      console.error(err);
    }
  };

  const addLead = async () => {
    try {
      await axios.post('/api/leads', { lead_data: newLead }, { headers: { Authorization: 'Bearer test-token' } });
      fetchLeads();
      setNewLead({ primary_identifier: '', vertical: '' });
    } catch (err) {
      console.error(err);
    }
  };

  const generateEmail = async (leadId) => {
    try {
      const res = await axios.post(`/api/leads/${leadId}/email-draft`, { template_id: 1 }, { headers: { Authorization: 'Bearer test-token' } });
      setEmailDraft(res.data);
      setSelectedLead(leadId);
    } catch (err) {
      console.error(err);
    }
  };

  const adjustScore = async (leadId) => {
    try {
      await axios.post(`/api/leads/${leadId}/adjust`, { ai_adjustment: adjustment }, { headers: { Authorization: 'Bearer test-token' } });
      fetchLeads();
      setAdjustment(0);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div style={{ padding: '20px' }}>
      <h1>ControlRoom MVP</h1>
      <h2>Zoznam leadov</h2>
      <table border="1" cellPadding="8" style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr><th>ID</th><th>Názov</th><th>Skóre</th><th>Tier</th><th>Akcie</th></tr>
        </thead>
        <tbody>
          {leads.map(lead => (
            <tr key={lead.id}>
              <td>{lead.id}</td>
              <td>{lead.primary_identifier}</td>
              <td>{lead.final_score}</td>
              <td>{lead.tier}</td>
              <td>
                <button onClick={() => generateEmail(lead.id)}>Generovať email</button>
                <input type="number" value={adjustment} onChange={(e) => setAdjustment(e.target.value)} placeholder="Adj." style={{ width: '50px' }} />
                <button onClick={() => adjustScore(lead.id)}>Upraviť skóre</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Pridať nového leada</h2>
      <input placeholder="Názov firmy" value={newLead.primary_identifier} onChange={(e) => setNewLead({ ...newLead, primary_identifier: e.target.value })} />
      <input placeholder="Vertikála" value={newLead.vertical} onChange={(e) => setNewLead({ ...newLead, vertical: e.target.value })} />
      <button onClick={addLead}>Pridať</button>

      {emailDraft && (
        <div style={{ marginTop: '20px', border: '1px solid gray', padding: '10px' }}>
          <h3>Návrh emailu pre leada {selectedLead}</h3>
          <p><strong>Predmet:</strong> {emailDraft.subject}</p>
          <p><strong>Text:</strong> {emailDraft.body}</p>
          <button onClick={() => setEmailDraft(null)}>Zavrieť</button>
        </div>
      )}
    </div>
  );
}

export default App;