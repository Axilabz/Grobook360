// In-app map screen for a Customer's captured GPS location (Leaflet +
// OpenStreetMap — free, no API key). Shows a pin on a real embedded map;
// the actual turn-by-turn navigation is handed off to Google Maps (no
// browser can simulate live GPS routing itself — same pattern delivery
// apps use: view the pin in-app, then open the device's own maps app for
// directions). If the customer has no location captured yet, shows an
// empty state prompting the user to add one instead of a blank map.
import React, { useEffect, useRef } from 'react';
import { X, Navigation2, MapPin, MapPinOff } from 'lucide-react';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';

// Leaflet's default marker icon references image files via a bundler-
// specific URL scheme that Vite doesn't resolve the same way webpack
// does — rebuild the icon URLs explicitly so the pin actually renders
// instead of showing a broken image (a well-known Leaflet+Vite gotcha).
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

export interface MapCustomer {
  id: string;
  name: string;
  address: string | null;
  city: string | null;
  gps_location: string | null;
}

export interface CustomerLocationMapProps {
  customer: MapCustomer;
  onClose: () => void;
  /** Called when the customer has no location yet and the user chooses to add one — the caller is responsible for opening the Edit Customer form. */
  onAddLocation: () => void;
}

// The GPS Location field stores a full Google Maps URL, e.g.
// "https://www.google.com/maps?q=12.9768,80.2214" — parse the lat/lng
// back out rather than adding a separate structured lat/lng column.
function parseLatLng(gpsLocation: string | null): { lat: number; lng: number } | null {
  if (!gpsLocation) return null;
  const match = gpsLocation.match(/q=(-?\d+\.?\d*),(-?\d+\.?\d*)/);
  if (!match) return null;
  const lat = Number(match[1]);
  const lng = Number(match[2]);
  if (Number.isNaN(lat) || Number.isNaN(lng)) return null;
  return { lat, lng };
}

const CustomerLocationMap: React.FC<CustomerLocationMapProps> = ({ customer, onClose, onAddLocation }) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const coords = parseLatLng(customer.gps_location);

  useEffect(() => {
    if (!coords || !mapContainerRef.current) return;

    const map = L.map(mapContainerRef.current, { center: [coords.lat, coords.lng], zoom: 16 });
    mapInstanceRef.current = map;

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map);

    L.marker([coords.lat, coords.lng])
      .addTo(map)
      .bindPopup(`<strong>${customer.name}</strong>${customer.address ? `<br/>${customer.address}` : ''}`)
      .openPopup();

    return () => {
      map.remove();
      mapInstanceRef.current = null;
    };
  }, [coords?.lat, coords?.lng, customer.name, customer.address]);

  const directionsUrl = coords
    ? `https://www.google.com/maps/dir/?api=1&destination=${coords.lat},${coords.lng}`
    : null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl w-full max-w-2xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <MapPin size={18} className="text-blue-600 dark:text-blue-400" />
            <h3 className="text-[16px] font-semibold text-gray-900 dark:text-white">{customer.name}</h3>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X size={20} />
          </button>
        </div>

        {coords ? (
          <>
            <div ref={mapContainerRef} className="w-full h-80" />
            <div className="flex items-center justify-between gap-3 px-5 py-4">
              <p className="text-[13px] text-gray-500 dark:text-gray-400 truncate">{customer.address || `${coords.lat.toFixed(5)}, ${coords.lng.toFixed(5)}`}</p>
              <a
                href={directionsUrl!}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 flex items-center gap-2 px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium whitespace-nowrap"
              >
                <Navigation2 size={15} /> Get Directions
              </a>
            </div>
          </>
        ) : (
          <div className="flex flex-col items-center justify-center gap-3 py-16 px-6 text-center">
            <MapPinOff size={36} className="text-gray-300 dark:text-gray-600" />
            <p className="text-[14px] font-medium text-gray-700 dark:text-gray-200">No location set for this customer</p>
            <p className="text-[13px] text-gray-500 dark:text-gray-400 max-w-xs">Add a GPS location so you can find this customer on the map and get directions.</p>
            <button
              onClick={onAddLocation}
              className="mt-2 px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium"
            >
              Add Location
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default CustomerLocationMap;
