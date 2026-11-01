// Major cities per Indian state/UT, keyed by the same GST state code used in
// gstStateCodes.ts. Not exhaustive — a practical starting list for the
// Sign-Up City dropdown. The City field still allows adding a new item
// (see Select's allowAddNew) for any city not listed here.
export const INDIA_STATE_CITIES: Record<string, string[]> = {
  '01': ['Srinagar', 'Jammu', 'Anantnag', 'Baramulla', 'Udhampur'],
  '02': ['Shimla', 'Dharamshala', 'Solan', 'Mandi', 'Kullu'],
  '03': ['Ludhiana', 'Amritsar', 'Jalandhar', 'Patiala', 'Bathinda', 'Mohali'],
  '04': ['Chandigarh'],
  '05': ['Dehradun', 'Haridwar', 'Rishikesh', 'Haldwani', 'Roorkee'],
  '06': ['Gurugram', 'Faridabad', 'Panipat', 'Ambala', 'Hisar', 'Rohtak', 'Karnal'],
  '07': ['New Delhi', 'Delhi'],
  '08': ['Jaipur', 'Jodhpur', 'Udaipur', 'Kota', 'Ajmer', 'Bikaner', 'Alwar'],
  '09': ['Lucknow', 'Kanpur', 'Noida', 'Ghaziabad', 'Agra', 'Varanasi', 'Meerut', 'Prayagraj'],
  '10': ['Patna', 'Gaya', 'Bhagalpur', 'Muzaffarpur', 'Darbhanga'],
  '11': ['Gangtok', 'Namchi', 'Gyalshing'],
  '12': ['Itanagar', 'Naharlagun', 'Pasighat'],
  '13': ['Kohima', 'Dimapur', 'Mokokchung'],
  '14': ['Imphal', 'Thoubal', 'Bishnupur'],
  '15': ['Aizawl', 'Lunglei', 'Champhai'],
  '16': ['Agartala', 'Udaipur', 'Dharmanagar'],
  '17': ['Shillong', 'Tura', 'Jowai'],
  '18': ['Guwahati', 'Dibrugarh', 'Silchar', 'Jorhat', 'Tezpur'],
  '19': ['Kolkata', 'Howrah', 'Durgapur', 'Asansol', 'Siliguri'],
  '20': ['Ranchi', 'Jamshedpur', 'Dhanbad', 'Bokaro', 'Hazaribagh'],
  '21': ['Bhubaneswar', 'Cuttack', 'Rourkela', 'Puri', 'Berhampur'],
  '22': ['Raipur', 'Bhilai', 'Bilaspur', 'Durg', 'Korba'],
  '23': ['Indore', 'Bhopal', 'Jabalpur', 'Gwalior', 'Ujjain'],
  '24': ['Ahmedabad', 'Surat', 'Vadodara', 'Rajkot', 'Bhavnagar', 'Gandhinagar'],
  '26': ['Silvassa', 'Daman', 'Diu'],
  '27': ['Mumbai', 'Pune', 'Nagpur', 'Nashik', 'Aurangabad', 'Thane', 'Solapur'],
  '28': ['Visakhapatnam', 'Vijayawada', 'Guntur'],
  '29': ['Bengaluru', 'Mysuru', 'Hubballi', 'Mangaluru', 'Belagavi', 'Davanagere'],
  '30': ['Panaji', 'Margao', 'Vasco da Gama'],
  '31': ['Kavaratti', 'Agatti'],
  '32': ['Kochi', 'Thiruvananthapuram', 'Kozhikode', 'Thrissur', 'Kollam', 'Kannur'],
  '33': ['Chennai', 'Coimbatore', 'Madurai', 'Tiruchirappalli', 'Salem', 'Erode', 'Tirunelveli', 'Vellore'],
  '34': ['Puducherry', 'Karaikal'],
  '35': ['Port Blair'],
  '36': ['Hyderabad', 'Warangal', 'Nizamabad', 'Karimnagar', 'Khammam'],
  '37': ['Visakhapatnam', 'Vijayawada', 'Guntur', 'Nellore', 'Tirupati', 'Kakinada'],
  '38': ['Leh', 'Kargil'],
};

// A practical, non-exhaustive classification for an FMCG distributor /
// wholesaler / retailer SaaS — not a controlled master list, so the City
// field pattern (Select + allowAddNew) is reused here too.
export const BUSINESS_TYPE_OPTIONS: string[] = [
  'Manufacturer',
  'Distributor',
  'Super Stockist',
  'Wholesaler',
  'Retailer',
  'Trader',
  'Other',
];
