import React, { useState, useEffect } from 'react';
import axios from 'axios';

function App() {
  const [leads, setLeads] = useState([]);
  const [newLead, setNewLead] = useState({ primary_identifier: '', vertical: '' });
  const [selectedLead, setSelectedLead] = useState(null);
  const [emailDraft, setEmailDraft] = useState(null);
  const [adjustment, setAdjustment] = useState(0);
  const [scrapeUrl, setScrapeUrl] = useState('');

  useEffect(() => {
    fetchLeads();
  }, []);

  const fetchLeads = async () => {
    try {
      const res = await axios.get('/api/leads', { headers: { Authorization: 'Bearer test-token' } });
      const sorted = res.data.sort((a, b) => b.final_score - a.final_score);
      setLeads(sorted);
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

  const handleScrape = async () => {
    if (!scrapeUrl) return;
    try {
      const res = await axios.post('/api/leads/scrape', { url: scrapeUrl }, { headers: { Authorization: 'Bearer test-token' } });
      alert(`Lead ${res.data.primary_identifier} bol pridaný so skóre ${res.data.score}`);
      fetchLeads();
      setScrapeUrl('');
    } catch (err) {
      console.error(err);
      alert('Chyba pri scrapovaní: ' + (err.response?.data?.detail || err.message));
    }
  };

  const getContactInfo = (lead) => {
    const channels = lead.contact_channels || {};
    const metadata = lead.lead_metadata || {};
    const phone = channels.phone || metadata.scraped_phone || '';
    const email = channels.email || metadata.scraped_email || '';
    const name = metadata.contact_name || metadata.scraped_contact_name || '';
    let position = '';
    const notes = metadata.notes || '';
    if (notes.toLowerCase().includes('ceo')) position = 'CEO';
    else if (notes.toLowerCase().includes('obchod')) position = 'Obchodné oddelenie';
    else if (name) position = 'Kontaktná osoba';
    return { phone, email, name, position };
  };

  return (
    <div style={{ padding: '20px' }}>
      <h1>ControlRoom MVP</h1>
      <h2>Zoznam leadov</h2>
      <table border="1" cellPadding="8" style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            <th>ID</th>
            <th>Názov</th>
            <th>Skóre</th>
            <th>Tier</th>
            <th>Telefón</th>
            <th>Email</th>
            <th>Kontaktná osoba</th>
            <th>Pozícia</th>
            <th>Akcie</th>
          </tr>
        </thead>
        <tbody>
          {leads.map(lead => {
            const { phone, email, name, position } = getContactInfo(lead);
            return (
              <tr key={lead.id}>
                <td>{lead.id}</td>
                <td>{lead.primary_identifier}</td>
                <td>{lead.final_score}</td>
                <td>{lead.tier}</td>
                <td>{phone}</td>
                <td>{email}</td>
                <td>{name}</td>
                <td>{position}</td>
                <td>
                  <button onClick={() => generateEmail(lead.id)}>Generovať email</button>
                  <input type="number" value={adjustment} onChange={(e) => setAdjustment(e.target.value)} placeholder="Adj." style={{ width: '60px', marginLeft: '5px' }} />
                  <button onClick={() => adjustScore(lead.id)}>Upraviť skóre</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h2>Pridať nového leada</h2>
      <input placeholder="Názov firmy" value={newLead.primary_identifier} onChange={(e) => setNewLead({ ...newLead, primary_identifier: e.target.value })} />
      <input placeholder="Vertikála" value={newLead.vertical} onChange={(e) => setNewLead({ ...newLead, vertical: e.target.value })} />
      <button onClick={addLead}>Pridať</button>

      <h2>Scrapni URL</h2>
      <input placeholder="https://..." value={scrapeUrl} onChange={(e) => setScrapeUrl(e.target.value)} style={{ width: '300px' }} />
      <button onClick={handleScrape}>Scrapni</button>

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