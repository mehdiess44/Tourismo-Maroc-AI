import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './style.css';

type Point = [number, number];
type Entity = {
  id:string; name:string; kind:string; aliases:string[]; related:string[];
  published_hours?:{text:string;url:string;checked_on:string};
  facts:{text:string;url:string;passage:string}[];
};
type Place = {name:string;position:Point};
type Route = {
  status:string; reason?:string; warnings:string[]; minutes?:number;
  geometry?:Point[]; departure_position?:Point;
  steps:{id:string;name:string;position:Point;start:string;walk:number;wait:number;visit:number}[];
};
type Recognition = {status:string;candidates:{id:string;score:number}[]};
const interests = [['architecture','Architecture'],['histoire','Histoire'],['musees','Musées'],['artisanat','Artisanat']];

async function api<T>(url:string, init?:RequestInit):Promise<T>{
  const response = await fetch(url, init);
  if (!response.ok) {
    const value = await response.json().catch(()=>({}));
    throw new Error(typeof value.detail==='string' ? value.detail : 'La demande a échoué. Vérifiez les champs et réessayez.');
  }
  return response.json();
}

function MapView({route,places}:{route:Route|null;places:Record<string,Place>}){
  const container = useRef<HTMLDivElement>(null);
  useEffect(()=>{
    const map = L.map(container.current!, {scrollWheelZoom:false}).setView([33.893,-5.563],15);
    const markers = L.layerGroup().addTo(map);
    const label = (pos:Point,name:string,color:string) => {
      const popup = document.createElement('span');
      popup.textContent = name;
      L.circleMarker(pos,{radius:6,color:'#fff',weight:2,fillColor:color,fillOpacity:1}).bindPopup(popup).addTo(markers);
    };
    if(route?.status==='ok' && route.geometry?.length){
      const line = L.polyline(route.geometry,{color:'#aa492a',weight:5}).addTo(markers);
      if(route.departure_position) label(route.departure_position,'Départ','#103e34');
      route.steps.forEach(step=>label(step.position,step.name,'#aa492a'));
      map.fitBounds(line.getBounds(),{padding:[24,24],maxZoom:17});
    } else {
      Object.values(places).forEach(place=>label(place.position,place.name,'#103e34'));
    }
    let active = true;
    api<GeoJSON.GeoJsonObject>('/map').then(data=>{
      if(active) L.geoJSON(data,{style:{color:'#a9b6a5',weight:1.5,opacity:.8}}).addTo(map).bringToBack();
    }).catch(()=>{});
    map.attributionControl.addAttribution('<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>');
    return ()=>{active=false;map.remove();};
  },[route,places]);
  return <div className="map" aria-label="Carte piétonne de Meknès" ref={container}/>;
}

function App(){
  const [tab,setTab] = useState('catalog');
  const [items,setItems] = useState<Entity[]>([]);
  const [places,setPlaces] = useState<Record<string,Place>>({});
  const [query,setQuery] = useState('');
  const [selected,setSelected] = useState<Entity|null>(null);
  const [result,setResult] = useState<Recognition|null>(null);
  const [route,setRoute] = useState<Route|null>(null);
  const [tripDeparture,setTripDeparture] = useState('');
  const [pending,setPending] = useState(false);
  const [error,setError] = useState('');
  useEffect(()=>{
    Promise.all([api<Entity[]>('/catalog'),api<Record<string,Place>>('/places')])
      .then(([entries,points])=>{setItems(entries);setPlaces(points);})
      .catch(()=>setError('Connexion au service impossible. Rechargez la page pour réessayer.'));
  },[]);
  const normalize = (v:string) => v.normalize('NFD').replace(/\p{Diacritic}/gu,'').toLowerCase();
  const visible = items.filter(item=>[item.name,...item.aliases].some(name=>normalize(name).includes(normalize(query.trim()))));
  async function submit(event:React.FormEvent<HTMLFormElement>,mode:string){
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError('');setPending(true);
    try {
      if(mode==='photo'){
        setResult(null);
        setResult(await api<Recognition>('/recognitions',{method:'POST',body:form}));
      } else {
        setRoute(null);
        const payload = Object.fromEntries(form);
        setRoute(await api<Route>('/itineraries',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({...payload,hours:Number(payload.hours),speed:Number(payload.speed),
            interests:form.getAll('interests'),required:form.getAll('required')})}));
      }
    } catch (err) {setError((err as Error).message);}
    finally {setPending(false);}
  }
  function open(id:string){
    setSelected(items.find(item=>item.id===id)??null);setTab('catalog');setError('');
  }
  const options = Object.entries(places).map(([id,place])=><option key={id} value={id}>{place.name}</option>);
  return <>
    <header><div className="brand"><span aria-hidden="true">✦</span> Tourismo AI</div><span>Guide de Meknès</span></header>
    <section className="hero"><div><p className="location">MÉDINA DE MEKNÈS</p><h1>Explorez Meknès</h1><p>Découvrez ses monuments et son artisanat, puis composez votre promenade à pied.</p></div></section>
    <main>
      <nav aria-label="Fonctions du guide">{[['catalog','Catalogue'],['photo','Identifier une photo'],['trip','Créer une promenade']].map(([id,label])=>
        <button key={id} aria-current={tab===id?'page':undefined} onClick={()=>{setTab(id);setError('');}}>{label}</button>)}</nav>
      {error && <p role="alert" className="notice">{error}</p>}
      {tab==='catalog' && <div className="split">
        <section><h2>Monuments et artisanat</h2><label>Rechercher dans le catalogue<input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Nom ou autre appellation"/></label>
          <div className="cards">{visible.map(item=><button key={item.id} className="card" onClick={()=>open(item.id)} aria-pressed={selected?.id===item.id}><small>{item.kind}</small>{item.name}</button>)}</div>
          {!visible.length && <p>Aucune fiche trouvée.</p>}</section>
        <section className="panel">{selected ? <><h2>{selected.name}</h2>{selected.facts.length?selected.facts.map(fact=><div className="fact" key={fact.text}><p>{fact.text}</p><a href={fact.url}>{fact.passage}</a></div>):<p>Les faits de cette fiche sont en cours de documentation.</p>}
          {selected.published_hours && <p>Horaires affichés par la source · {selected.published_hours.text}. <a href={selected.published_hours.url}>Source consultée le {selected.published_hours.checked_on}</a></p>}
          {places[selected.id] && <p><button onClick={()=>{setTripDeparture(selected.id);setTab('trip');setRoute(null);}}>Partir de ce lieu</button></p>}
          {selected.related.map(id=><button key={id} onClick={()=>open(id)}>{items.find(i=>i.id===id)?.name??id}</button>)}</>:<><h2>Fiche patrimoniale</h2><p>Sélectionnez un lieu ou une famille artisanale pour consulter sa fiche et ses sources.</p></>}</section>
      </div>}
      {tab==='photo' && <div className="split"><form className="panel" onSubmit={e=>submit(e,'photo')}><h2>Identifier une photo</h2>
        <label>Type de sujet<select name="kind"><option value="monument">Monument</option><option value="artisanat">Artisanat</option></select></label>
        <label>Photo <small>JPEG, PNG ou WebP · 5 Mio maximum</small><input type="file" name="photo" accept="image/jpeg,image/png,image/webp" required/></label>
        <button className="primary" disabled={pending}>{pending?'Analyse en cours…':'Analyser la photo'}</button></form>
        <section className="panel" aria-live="polite"><h2>Résultat de la recherche</h2>
          {result && <p>{result.status==='unavailable'?'Le modèle visuel est indisponible.':result.status==='uncertain'?'Identification incertaine. Vérifiez les candidats.':'Vérifiez et confirmez le candidat proposé.'}</p>}
          {result?.candidates.map(candidate=><button key={candidate.id} className="candidate" onClick={()=>open(candidate.id)}>{items.find(i=>i.id===candidate.id)?.name??candidate.id} <small>Score {candidate.score.toFixed(2)}</small></button>)}
          <button onClick={()=>setTab('catalog')}>Choisir une fiche manuellement</button>
        </section></div>}
      {tab==='trip' && <div className="split"><form className="panel" onSubmit={e=>submit(e,'trip')}><h2>Créer une promenade</h2>
        {!options.length && <p className="notice">Le réseau piéton est indisponible.</p>}
        <div className="fields"><label>Départ<select name="departure" required value={tripDeparture || Object.keys(places)[0] || ''} onChange={e=>setTripDeparture(e.target.value)}>{options}</select></label><label>Arrivée<select name="arrival" required>{options}</select></label>
        <label>Date<input type="date" name="day" required/></label><label>Heure à Meknès<input type="time" name="start" defaultValue="10:00" required/></label>
        <label>Durée maximale<select name="hours" defaultValue="3">{[1,2,3,4,5,6].map(h=><option key={h} value={h}>{h} h</option>)}</select></label>
        <label>Rythme<select name="speed" defaultValue="4"><option value="3">Tranquille · 3 km/h</option><option value="4">Modéré · 4 km/h</option><option value="5">Soutenu · 5 km/h</option></select></label></div>
        <fieldset><legend>Centres d’intérêt</legend>{interests.map(([id,label])=><label className="check" key={id}><input type="checkbox" name="interests" value={id}/>{label}</label>)}</fieldset>
        <details><summary>Étapes obligatoires</summary>{Object.entries(places).map(([id,p])=><label className="check" key={id}><input type="checkbox" name="required" value={id}/>{p.name}</label>)}</details>
        <button className="primary" disabled={pending||!options.length}>{pending?'Calcul en cours…':'Calculer la promenade'}</button>
      </form><section className="panel"><h2>Votre parcours</h2><MapView places={places} route={route}/>
        <div aria-live="polite">{route?.status==='ok'?<><h3>{route.minutes} min estimées</h3>
        <ol>{route.steps.map((step,i)=><li key={i}><strong>{step.name}</strong> · {step.start.slice(11,16)}<br/><small>Marche {step.walk} min · Attente {step.wait} min · Visite {step.visit} min</small></li>)}</ol>
        {route.warnings.map(w=><p className="notice" key={w}>{w}</p>)}</>:<p>{route?.reason??'Indiquez votre départ, votre arrivée et le temps disponible.'}</p>}</div>
      </section></div>}
    </main><footer>Tourismo AI · Pilote de Meknès</footer>
  </>;
}

createRoot(document.getElementById('root')!).render(<App/>);
