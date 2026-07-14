import React from 'react';
import { useParams } from 'react-router-dom';

export default function IncidentDetails() {
  const { id } = useParams();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold text-gray-900">Incident Details {id ? `#${id}` : ''}</h1>
        <span className="px-3 py-1 text-sm font-semibold text-red-800 bg-red-100 rounded-full">Critical</span>
      </div>
      <div className="p-6 bg-white rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">Description</h2>
        <p className="text-gray-700">Detailed information about the incident will go here.</p>
      </div>
    </div>
  );
}
