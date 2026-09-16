// Power-system archetypes (SOW §1.2) with the colours and icons from the Claude Design project
// "Power System Archetype Icons" (cc0faa3d-2aea-43fd-b916-7d480ef1bf1b). Icons are drawn on a
// 48-unit grid, stroke only; `icon` is the inner SVG markup, stroke colour and width are applied
// by the page. Data versions (data/layers/*.js) reference these by id.
window.ARCHETYPES = [
  {
    id: 'dense',
    name: 'Renewables-constrained, high-density',
    short: 'RE-constrained, dense',
    examples: 'Western Europe · South Korea · Japan',
    color: '#0B9E45', tint: '#DFF3E5',
    icon: '<line x1="5" y1="42" x2="43" y2="42"/><rect x="8" y="24" width="9" height="18"/><rect x="21" y="14" width="9" height="28"/><rect x="34" y="28" width="9" height="14"/><circle cx="38.5" cy="17" r="4"/><line x1="38.5" y1="11" x2="38.5" y2="7.5"/><line x1="34.2" y1="12.7" x2="31.7" y2="10.2"/><line x1="42.8" y1="12.7" x2="45.3" y2="10.2"/>'
  },
  {
    id: 'geothermal',
    name: 'Geothermal-favourable',
    short: 'Geothermal-favourable',
    examples: 'US West · SE Asia · Turkey · Italy',
    color: '#E8380D', tint: '#FCE7DF',
    icon: '<line x1="5" y1="9" x2="43" y2="9"/><path d="M20 9 V29 L24 37 L28 29 V9"/><line x1="20" y1="15.5" x2="28" y2="13.5"/><line x1="20" y1="21.5" x2="28" y2="19.5"/><line x1="20" y1="27.5" x2="28" y2="25.5"/><path d="M10 41 q5 -4 0 -9.5 t0 -9.5"/><path d="M38 41 q5 -4 0 -9.5 t0 -9.5"/>'
  },
  {
    id: 'islanded',
    name: 'Islanded / weak interconnection',
    short: 'Islanded / weak grid',
    examples: 'Western Australia · Ireland',
    color: '#DB2777', tint: '#FBE3EF',
    icon: '<path d="M11 36 q13 -13 26 0"/><line x1="3" y1="36" x2="8" y2="36"/><line x1="40" y1="36" x2="45" y2="36"/><path d="M14 41.5 q3.5 -3 7 0 t7 0 t7 0"/><path d="M23.5 33 q-1.5 -8 2.5 -16"/><path d="M26 17 q-8 -3 -12 3"/><path d="M26 17 q8 -3 12 3"/><path d="M26 17 q-4 -6 -9 -7"/><path d="M26 17 q5 -5 10 -4"/>'
  },
  {
    id: 'hydro',
    name: 'Hydro-rich',
    short: 'Hydro-rich',
    examples: 'Norway · Brazil · Canada',
    color: '#1D4ED8', tint: '#E1E8FB',
    icon: '<path d="M20 5.5 C17.5 9.5 13 14.5 13 19.5 a7 7 0 0 0 14 0 C27 14.5 22.5 9.5 20 5.5 Z"/><path d="M16.5 20 q3.5 -2.5 7 0"/><path d="M4 42 L14 30.5 L20 36.5 L30 27.5 L44 42"/><line x1="4" y1="42" x2="44" y2="42"/>'
  },
  {
    id: 'fossil',
    name: 'Fossil-heavy brownfield',
    short: 'Fossil-heavy brownfield',
    examples: 'US · India · parts of Europe',
    color: '#A85B00', tint: '#F5EBD9',
    icon: '<line x1="5" y1="42" x2="43" y2="42"/><path d="M9 42 V27 L16.5 22 V27 L24 22 V27 H31"/><path d="M31 42 V11 H38 V42"/><circle cx="34.5" cy="5.5" r="2.2"/>'
  }
  ,
  // ---- data-derived clusters (scripts/sep/cluster_tsne.py, k-means k=5 on engineered SOW features).
  // In SOW §1.2 order (the islanded slot taken by high renewables potential), colours as in cluster_tsne.png. Icons in the same 48-unit stroke style.
  {
    id: 'k_densefossil',
    name: 'Renewables-constrained, high-density',
    short: 'RE-constrained, dense',
    examples: 'China · South Korea · Germany · UK · Spain · Poland',
    color: '#A85B00', tint: '#F5EBD9',
    icon: '<line x1="5" y1="42" x2="43" y2="42"/><rect x="7" y="26" width="8" height="16"/><rect x="18" y="16" width="9" height="26"/><rect x="30" y="22" width="6" height="20"/><path d="M39 42 V11 H43 V42"/><circle cx="41" cy="5.5" r="2.2"/><line x1="11" y1="31" x2="11" y2="33"/><line x1="22.5" y1="21" x2="22.5" y2="23"/><line x1="22.5" y1="28" x2="22.5" y2="30"/>'
  },
  {
    id: 'k_geo',
    name: 'Geothermal-favourable',
    short: 'Geothermal-favourable',
    examples: 'US West · Japan · Indonesia · Mexico · Türkiye · Italy',
    color: '#E8380D', tint: '#FCE7DF',
    icon: '<line x1="5" y1="9" x2="43" y2="9"/><path d="M20 9 V29 L24 37 L28 29 V9"/><line x1="20" y1="15.5" x2="28" y2="13.5"/><line x1="20" y1="21.5" x2="28" y2="19.5"/><line x1="20" y1="27.5" x2="28" y2="25.5"/><path d="M10 41 q5 -4 0 -9.5 t0 -9.5"/><path d="M38 41 q5 -4 0 -9.5 t0 -9.5"/>'
  },
  {
    // display-only in the k-means layer (no cluster behind it): the SOW's islanded archetype, modelled by Singapore
    id: 'k_islanded',
    name: 'Islanded / weakly interconnected',
    short: 'Islanded',
    examples: 'Singapore · Western Australia · Ireland',
    color: '#6B7280', tint: '#ECEEF1',
    icon: '<path d="M8 36 q16 -14 32 0"/><line x1="2" y1="36" x2="6" y2="36"/><line x1="42" y1="36" x2="46" y2="36"/><path d="M10 42 q3.5 -3 7 0 t7 0 t7 0 t7 0"/><path d="M26 33 q-1 -9 3 -17"/><path d="M29 16 q-9 -3 -13 4"/><path d="M29 16 q9 -3 13 4"/><path d="M29 16 q-5 -6 -10 -6"/><path d="M29 16 q5 -6 10 -5"/><path d="M29 16 q-1 -6 2 -9"/>'
  },
  {
    id: 'k_growth',
    name: 'High renewables potential',
    short: 'High RE potential',
    examples: 'India · Pakistan · Egypt · Bangladesh · Nigeria',
    color: '#DB2777', tint: '#FBE3EF',
    icon: '<line x1="5" y1="42" x2="43" y2="42"/><rect x="8" y="31" width="7" height="11"/><rect x="19" y="24" width="7" height="18"/><rect x="30" y="16" width="7" height="26"/><path d="M8 20 L20 13 L28 16 L42 6"/><path d="M35 6 H42 V13"/>'
  },
  {
    id: 'k_cleanfirm',
    name: 'Hydro-rich',
    short: 'Hydro-rich',
    examples: 'Brazil · France · Ethiopia · DR Congo · Sweden · Norway',
    color: '#1D4ED8', tint: '#E1E8FB',
    icon: '<path d="M15 5.5 C12.5 9.5 8 14.5 8 19.5 a7 7 0 0 0 14 0 C22 14.5 17.5 9.5 15 5.5 Z"/><circle cx="34" cy="16" r="8"/><circle cx="34" cy="16" r="1.8"/><path d="M4 42 L14 30.5 L20 36.5 L30 27.5 L44 42"/><line x1="4" y1="42" x2="44" y2="42"/>'
  },
  {
    id: 'k_sparse',
    name: 'Fossil-heavy brownfield with large economies',
    short: 'Fossil-heavy brownfield',
    examples: 'US East · Russia · Canada · ERCOT · Saudi Arabia · Australia NEM',
    color: '#0B9E45', tint: '#DFF3E5',
    icon: '<circle cx="24" cy="25" r="16"/><path d="M26.5 14 L18.5 27 H25 L21.5 36 L30 23 H23.5 Z"/><line x1="24" y1="4" x2="24" y2="9"/><line x1="24" y1="41" x2="24" y2="46"/><line x1="3" y1="25" x2="8" y2="25"/><line x1="40" y1="25" x2="45" y2="25"/>'
  }
];
window.ARCHETYPE_STROKE = 3;   // design default stroke width on the 48-unit grid
