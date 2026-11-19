/// Data for the world map, the same as the WebView UI's (nobadvpn/ui/app.js): the land mask and the offline
/// place tables. Generated from app.js; do not edit by hand.
library;

/// Land mask: 160 x 62 cells, 1 bit each, row-major, from latitude 83 down 140 degrees.
const landCols = 160;
const landRows = 62;
const mapLat0 = 83.0;
const mapLatSpan = 140.0;

const landBase64 =
    'AAAAAAP/////wAAAAAAAAAAAAAAAAAAAB/////8AB/AEAAB8AAAAAAAAADM//P///wADQAAEAA+AAAAAAAAAb5/4A///AAAAAHgD'
    '/+AHAAAAAAD/3/4B//4AAAABg3///4PAAID/gV/u/8H//AAAfACH//////4Aw//////z4P/wAAH/2//////////3/////+P4/4fA'
    'B////////////wn/////9+B8A4Af////////////A/////4HgDgAAD9///////////wB/H///AfwAAAAPz/////////5gABwD///'
    'g/gAAAYff////////AeAAQAH///3/gAADx/////////4BwAAAAH///f/AAAPv/////////8GAAAAAf////8AAAP//////////wAA'
    'AAAA////94AAA//////////9AAAAAAB////4AAAB///9//////kAAAAAAP///4AAAA//+Hv/////84AAAAAA////gAAAD5///f//'
    '///CAAAAAAB///4AAAAPAX/9////+4IAAAAAAD///gAAAA/6b//////8zgAAAAAAP//8AAAAB/gB//////y8AAAAAAAP//gAAAAP'
    '/nH//////CAAAAAAAA//8AAAAB/////////8AAAAAAAAB/gYAAAAP////f////wAAAAAAAAD+AwAAAB////+/////AAAAAAAAAD4'
    'GAAAAH///3/j///0AAAAACAAAHjGAAAA/////8H+f8AAAAAAAAAAf4XgAAD///+/wPx+gAAAAAAAAAAf4AAAAP///98A+D8GAAAA'
    'AAAAAAHgAAAA/////ABwH4YAAAAAAAAAAGGAAAD////2AHAPgwAAAAAAAAAAP/gAAH////4AMBsLAAAAAAAAAAAf/AAAP////AAY'
    'CAOAAAAAAAAAAAf/gAAfP//8AAA8GAAAAAAAAAAAB//AAAAP//gAABx4AAAAAAAAAAAP/8AAAA//8AAADP6AAAAAAAAAAA//+AAA'
    'D//gAAAG9jQAAAAAAAAAD//+AAAP/8AAAAYW35AAAAAAAAAP//+AAAf/wAAAA8AH8AAAAAAAAAf//4AAB//AAAAA7QdDAAAAAAAA'
    'B///AAAD/8AAAAAAACAAAAAAAAAD//4AAAf/xAAAAAA5AAAAAAAAAAP//gAAB//OAAAAAfmAIAAAAAAAAP/+AAAH/5wAAAAD/4AB'
    'AAAAAAAA//wAAAf/HAAAAA//wAAAAAAAAAB//AAAA/8cAAAAP//gQAAAAAAAAP/wAAAD/xgAAAA///AAAAAAAAAA/+AAAAP+AAAA'
    'AD//8AAAAAAAAAD/wAAAAf4AAAAAH//4AAAAAAAAAP/AAAAA/AAAAAAf//AAAAAAAAAA/4AAAAD4AAAAAB8f8AAAAAAAAAH+AAAA'
    'AAAAAAAAAAfgBAAAAAAAAf4AAAAAAAAAAAAAA+AHAAAAAAAB+AAAAAAAAAAAAAAAAAYAAAAAAAHwAAAAAAAAAAAAAADADAAAAAAA'
    'AeAAAAAAAAAAAAAAAAA4AAAAAAAD4AAAAAAAAAAAAAAAADAAAAAAAAPAAAAAAAAAAgAAAAAAAAAAAAAAA8QAAAAAAAAAAAAAAAAA'
    'AAAAAAABwAAAAAAAAAAAAAAAAAAAAAAAAABgAAAAAAAAAAAAAAAAAA==';

/// "name lat lon" entries, comma separated.
const cityTable =
    'newyork 40.71 -74.01,losangeles 34.05 -118.24,chicago 41.88 -87.63,dallas 32.78 -96.8,miami 25.76 -8'
    '0.19,seattle 47.61 -122.33,sanfrancisco 37.77 -122.42,sanjose 37.34 -121.89,siliconvalley 37.39 -122'
    '.03,denver 39.74 -104.99,atlanta 33.75 -84.39,phoenix 33.45 -112.07,lasvegas 36.17 -115.14,boston 42'
    '.36 -71.06,washington 38.9 -77.04,ashburn 39.04 -77.49,newjersey 40.06 -74.41,secaucus 40.79 -74.06,'
    'houston 29.76 -95.37,saltlakecity 40.76 -111.89,kansascity 39.1 -94.58,buffalo 42.89 -78.88,portland'
    ' 45.52 -122.68,charlotte 35.23 -80.84,toronto 43.65 -79.38,montreal 45.5 -73.57,vancouver 49.28 -123'
    '.12,calgary 51.05 -114.07,mexicocity 19.43 -99.13,saopaulo -23.55 -46.63,riodejaneiro -22.91 -43.17,'
    'buenosaires -34.6 -58.38,santiago -33.45 -70.67,bogota 4.71 -74.07,lima -12.05 -77.04,london 51.51 -'
    '0.13,manchester 53.48 -2.24,dublin 53.35 -6.26,paris 48.86 2.35,marseille 43.3 5.37,amsterdam 52.37 '
    '4.9,rotterdam 51.92 4.48,brussels 50.85 4.35,frankfurt 50.11 8.68,berlin 52.52 13.4,munich 48.14 11.'
    '58,hamburg 53.55 9.99,dusseldorf 51.23 6.78,nuremberg 49.45 11.08,falkenstein 50.48 12.37,zurich 47.'
    '38 8.54,geneva 46.2 6.14,vienna 48.21 16.37,prague 50.08 14.44,warsaw 52.23 21.01,budapest 47.5 19.0'
    '4,bucharest 44.43 26.1,sofia 42.7 23.32,belgrade 44.79 20.45,zagreb 45.81 15.98,athens 37.98 23.73,m'
    'ilan 45.46 9.19,rome 41.9 12.5,madrid 40.42 -3.7,barcelona 41.39 2.17,lisbon 38.72 -9.14,copenhagen '
    '55.68 12.57,stockholm 59.33 18.07,oslo 59.91 10.75,helsinki 60.17 24.94,tallinn 59.44 24.75,riga 56.'
    '95 24.11,vilnius 54.69 25.28,kyiv 50.45 30.52,kiev 50.45 30.52,moscow 55.76 37.62,stpetersburg 59.93'
    ' 30.34,istanbul 41.01 28.98,telaviv 32.09 34.78,dubai 25.2 55.27,abudhabi 24.45 54.38,doha 25.29 51.'
    '53,riyadh 24.71 46.68,cairo 30.04 31.24,johannesburg -26.2 28.05,capetown -33.92 18.42,lagos 6.52 3.'
    '38,nairobi -1.29 36.82,casablanca 33.57 -7.59,mumbai 19.08 72.88,bombay 19.08 72.88,newdelhi 28.61 7'
    '7.21,delhi 28.61 77.21,bangalore 12.97 77.59,bengaluru 12.97 77.59,chennai 13.08 80.27,hyderabad 17.'
    '39 78.49,kolkata 22.57 88.36,pune 18.52 73.86,noida 28.54 77.39,karachi 24.86 67,lahore 31.55 74.34,'
    'dhaka 23.81 90.41,colombo 6.93 79.86,kathmandu 27.72 85.32,singapore 1.35 103.82,kualalumpur 3.14 10'
    '1.69,jakarta -6.21 106.85,bangkok 13.76 100.5,hanoi 21.03 105.85,hochiminh 10.82 106.63,saigon 10.82'
    ' 106.63,manila 14.6 120.98,hongkong 22.32 114.17,taipei 25.03 121.57,tokyo 35.68 139.69,osaka 34.69 '
    '135.5,seoul 37.57 126.98,beijing 39.9 116.4,shanghai 31.23 121.47,shenzhen 22.54 114.06,sydney -33.8'
    '7 151.21,melbourne -37.81 144.96,brisbane -27.47 153.03,perth -31.95 115.86,auckland -36.85 174.76,a'
    'lmaty 43.24 76.89,tbilisi 41.72 44.78,yerevan 40.18 44.51,baku 40.41 49.87,reykjavik 64.15 -21.94,lu'
    'xembourg 49.61 6.13,panamacity 8.98 -79.52';

const countryTable =
    'usa 39 -98,unitedstates 39 -98,america 39 -98,uk 51.5 -0.1,unitedkingdom 51.5 -0.1,britain 51.5 -0.1'
    ',england 51.5 -0.1,germany 50.1 8.7,france 48.9 2.4,netherlands 52.4 4.9,holland 52.4 4.9,japan 35.7'
    ' 139.7,india 19.1 72.9,australia -33.9 151.2,canada 43.7 -79.4,brazil -23.5 -46.6,korea 37.6 127,sou'
    'thkorea 37.6 127,switzerland 47.4 8.5,sweden 59.3 18.1,norway 59.9 10.75,finland 60.2 24.9,denmark 5'
    '5.7 12.6,spain 40.4 -3.7,portugal 38.7 -9.1,italy 45.5 9.2,ireland 53.3 -6.3,belgium 50.85 4.35,aust'
    'ria 48.2 16.4,poland 52.2 21,czechia 50.1 14.4,czech 50.1 14.4,hungary 47.5 19,romania 44.4 26.1,bul'
    'garia 42.7 23.3,greece 38 23.7,serbia 44.8 20.5,croatia 45.8 16,estonia 59.4 24.75,latvia 56.95 24.1'
    ',lithuania 54.7 25.3,iceland 64.1 -21.9,turkey 41 29,turkiye 41 29,israel 32.1 34.8,uae 25.2 55.3,em'
    'irates 25.2 55.3,saudiarabia 24.7 46.7,saudi 24.7 46.7,qatar 25.3 51.5,bahrain 26.1 50.6,egypt 30 31'
    '.2,southafrica -26.2 28.05,nigeria 6.5 3.4,kenya -1.3 36.8,morocco 33.6 -7.6,russia 55.8 37.6,ukrain'
    'e 50.45 30.5,mexico 19.4 -99.1,argentina -34.6 -58.4,chile -33.45 -70.7,colombia 4.7 -74.1,peru -12 '
    '-77,china 31.2 121.5,taiwan 25 121.6,thailand 13.8 100.5,vietnam 21 105.85,malaysia 3.1 101.7,indone'
    'sia -6.2 106.85,philippines 14.6 121,pakistan 24.9 67,bangladesh 23.8 90.4,srilanka 6.9 79.9,nepal 2'
    '7.7 85.3,newzealand -36.85 174.8,kazakhstan 43.2 76.9,armenia 40.2 44.5,azerbaijan 40.4 49.9,panama '
    '8.98 -79.5,hongkong 22.3 114.2,singapore 1.35 103.8';

/// "code=name" aliases: airport codes to cities, ISO country codes to countries.
const airportTable =
    'nyc=newyork,jfk=newyork,ewr=newyork,lax=losangeles,sfo=sanfrancisco,sjc=sanjose,sea=seattle,ord=chic'
    'ago,chi=chicago,dfw=dallas,dal=dallas,mia=miami,atl=atlanta,iad=ashburn,was=washington,den=denver,ph'
    'x=phoenix,las=lasvegas,bos=boston,iah=houston,slc=saltlakecity,yyz=toronto,yul=montreal,yvr=vancouve'
    'r,yyc=calgary,mex=mexicocity,gru=saopaulo,sao=saopaulo,gig=riodejaneiro,eze=buenosaires,scl=santiago'
    ',bog=bogota,lim=lima,lhr=london,lon=london,man=manchester,dub=dublin,cdg=paris,par=paris,mrs=marseil'
    'le,ams=amsterdam,rtm=rotterdam,bru=brussels,fra=frankfurt,ber=berlin,muc=munich,ham=hamburg,dus=duss'
    'eldorf,nue=nuremberg,zrh=zurich,gva=geneva,vie=vienna,prg=prague,waw=warsaw,bud=budapest,otp=buchare'
    'st,buh=bucharest,sof=sofia,beg=belgrade,zag=zagreb,ath=athens,mxp=milan,mil=milan,fco=rome,rom=rome,'
    'mad=madrid,bcn=barcelona,lis=lisbon,cph=copenhagen,arn=stockholm,sto=stockholm,osl=oslo,hel=helsinki'
    ',tll=tallinn,rix=riga,vno=vilnius,kbp=kyiv,iev=kyiv,svo=moscow,mow=moscow,led=stpetersburg,ist=istan'
    'bul,tlv=telaviv,dxb=dubai,auh=abudhabi,doh=doha,ruh=riyadh,cai=cairo,jnb=johannesburg,cpt=capetown,l'
    'os=lagos,nbo=nairobi,cmn=casablanca,bom=mumbai,del=delhi,blr=bangalore,maa=chennai,hyd=hyderabad,ccu'
    '=kolkata,pnq=pune,khi=karachi,lhe=lahore,dac=dhaka,cmb=colombo,ktm=kathmandu,sin=singapore,kul=kuala'
    'lumpur,cgk=jakarta,jkt=jakarta,bkk=bangkok,han=hanoi,sgn=hochiminh,mnl=manila,hkg=hongkong,tpe=taipe'
    'i,nrt=tokyo,hnd=tokyo,tyo=tokyo,kix=osaka,osa=osaka,icn=seoul,sel=seoul,pek=beijing,bjs=beijing,pvg='
    'shanghai,sha=shanghai,szx=shenzhen,syd=sydney,mel=melbourne,bne=brisbane,per=perth,akl=auckland,ala='
    'almaty,tbs=tbilisi,evn=yerevan,gyd=baku,kef=reykjavik,lux=luxembourg,pty=panamacity';

const isoTable =
    'us=usa,gb=uk,de=germany,fr=france,nl=netherlands,jp=japan,in=india,sg=singapore,au=australia,ca=cana'
    'da,br=brazil,kr=korea,hk=hongkong,ch=switzerland,se=sweden,no=norway,fi=finland,dk=denmark,es=spain,'
    'pt=portugal,it=italy,ie=ireland,be=belgium,at=austria,pl=poland,cz=czechia,hu=hungary,ro=romania,bg='
    'bulgaria,gr=greece,rs=serbia,hr=croatia,ee=estonia,lv=latvia,lt=lithuania,is=iceland,tr=turkey,il=is'
    'rael,ae=uae,sa=saudiarabia,qa=qatar,bh=bahrain,eg=egypt,za=southafrica,ng=nigeria,ke=kenya,ma=morocc'
    'o,ru=russia,ua=ukraine,mx=mexico,ar=argentina,cl=chile,co=colombia,pe=peru,cn=china,tw=taiwan,th=tha'
    'iland,vn=vietnam,my=malaysia,id=indonesia,ph=philippines,pk=pakistan,bd=bangladesh,lk=srilanka,np=ne'
    'pal,nz=newzealand,kz=kazakhstan,am=armenia,az=azerbaijan,pa=panama,lu=luxembourg';
