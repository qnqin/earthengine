import ee, getpass, time, math, sys
from flask import Flask, render_template, request 
from eeMad import imad
from eeWishart import omnibus

# Set to True for localhost, False for appengine deploy
local = True

centerlon = 8.5
centerlat = 50.05
jet = 'black,blue,cyan,yellow,red'

if local:
# for local flask server
    ee.Initialize()
    msg = 'Choose a rectangular region'
else:
# for appengine deployment or development appserver
    import config
    ee.Initialize(config.EE_CREDENTIALS, 'https://earthengine.googleapis.com')
    msg = 'Choose a rectangular region.<br />Exporting results is not possible.'

app = Flask(__name__)

#------------------
# helper functions
#------------------

def get_vv(image):   
    ''' get 'VV' band from sentinel-1 imageCollection and restore linear signal from db-values '''
    return image.select('VV').multiply(ee.Image.constant(math.log(10.0)/10.0)).exp()

def get_vh(image):   
    ''' get 'VH' band from sentinel-1 imageCollection and restore linear signal from db-values '''
    return image.select('VH').multiply(ee.Image.constant(math.log(10.0)/10.0)).exp()

def get_vvvh(image):   
    ''' get 'VV' and 'VH' bands from sentinel-1 imageCollection and restore linear signal from db-values '''
    return image.select('VV','VH').multiply(ee.Image.constant(math.log(10.0)/10.0)).exp()

def get_vvvh_raw(image):
    return image.select('VV','VH')

def get_image(current,image):
        ''' accumulate a single image from a collection of images '''
        return ee.Image.cat(ee.Image(image),current)    
    
def clipList(current,prev):
    imlist = ee.List(ee.Dictionary(prev).get('imlist'))
    rect = ee.Dictionary(prev).get('rect')    
    imlist = imlist.add(ee.Image(current).clip(rect))
    return ee.Dictionary({'imlist':imlist,'rect':rect})

#--------------------
# request handlers
#--------------------

@app.route('/')
def index():
    return app.send_static_file('index.html')
    
@app.route('/sentinel1.html', methods = ['GET', 'POST'])
def Sentinel1():    
    global msg, centerlon, centerlat, local
    if request.method == 'GET':
        if local:
            return render_template('sentinel1.html', msg = msg,
                                                 centerlon = centerlon,
                                                 centerlat = centerlat)
        else:
            return render_template('sentinel1web.html', msg = msg,
                                                 centerlon = centerlon,
                                                 centerlat = centerlat)
    else:
        try: 
            startdate = request.form['startdate']  
            enddate = request.form['enddate']
            orbit = request.form['orbit']
            polarization1 = request.form['polarization']
            relativeorbitnumber = request.form['relativeorbitnumber']
            if polarization1 == 'VV,VH':
                polarization = ['VV','VH']
            else:
                polarization = polarization1
            mode = request.form['mode']
            minLat = float(request.form['minLat'])
            minLon = float(request.form['minLon'])
            maxLat = float(request.form['maxLat'])
            maxLon = float(request.form['maxLon'])
            if request.form.has_key('export'):        
                export = request.form['export']
            else:
                export = 'none'
            gdexportname = request.form['exportname']
            gdexportscale = float(request.form['gdexportscale'])
            start = ee.Date(startdate)
            finish = ee.Date(enddate)    
            rect = ee.Geometry.Rectangle(minLon,minLat,maxLon,maxLat)     
            centerlon = (minLon + maxLon)/2.0
            centerlat = (minLat + maxLat)/2.0 
            ulPoint = ee.Geometry.Point([minLon,maxLat])   
            lrPoint = ee.Geometry.Point([maxLon,minLat])
            collection = ee.ImageCollection('COPERNICUS/S1_GRD') \
                        .filterBounds(ulPoint) \
                        .filterBounds(lrPoint) \
                        .filterDate(start, finish) \
                        .filter(ee.Filter.eq('transmitterReceiverPolarisation', polarization)) \
                        .filter(ee.Filter.eq('resolution_meters', 10)) \
                        .filter(ee.Filter.eq('instrumentMode', mode)) \
                        .filter(ee.Filter.eq('orbitProperties_pass', orbit))                        
            if relativeorbitnumber != '':
                collection = collection.filter(ee.Filter.eq('relativeOrbitNumber_start', int(relativeorbitnumber))) 
            collection = collection.sort('system:time_start')                           
            system_ids = ee.List(collection.aggregate_array('system:id'))                  
            systemidlist = []
            for systemid in system_ids.getInfo():
                systemidlist.append(systemid) 
            systemids = str(systemidlist)                                        
            acquisition_times = ee.List(collection.aggregate_array('system:time_start'))                                           
            count = acquisition_times.length().getInfo() 
            if count==0:
                raise ValueError('No images found')   
            timestamplist = []
            for timestamp in acquisition_times.getInfo():
                tmp = time.gmtime(int(timestamp)/1000)
                timestamplist.append(time.strftime('%c', tmp))
            timestamp = timestamplist[0]    
            timestamps = str(timestamplist)    
            relative_orbit_numbers = ee.List(collection.aggregate_array('relativeOrbitNumber_start'))             
            relativeorbitnumberlist = []
            for ron  in relative_orbit_numbers.getInfo():
                relativeorbitnumberlist.append(ron)
            relativeorbitnumbers = str(relativeorbitnumberlist)                                                 
            image = ee.Image(collection.first())                       
            systemid = image.get('system:id').getInfo()   
            if (polarization1 == 'VV') or (polarization1 == 'VV,VH'): 
                projection = image.select('VV').projection().getInfo()['crs']
            else:
                projection = image.select('VH').projection().getInfo()['crs']    
#          make into collection of VV, VH or VVVH images and restore linear scale             
            if polarization == 'VV':
                pcollection = collection.map(get_vv)
            elif polarization == 'VH':
                pcollection = collection.map(get_vh)
            else:
                pcollection = collection.map(get_vvvh)
                # pcollection = collection.map(get_vvvh_raw) 
#          clipped image for display on map                
            image1 = ee.Image(pcollection.first())  
            image1clip = image1.clip(rect)        
            downloadpath = image1.getDownloadUrl({'scale':30})                                                             
#          clip the image collection and create a single multiband image      
            compositeimage = ee.Image(pcollection.iterate(get_image,image1clip))                            
            if export == 'export':
#              export to Google Drive --------------------------
                gdexport = ee.batch.Export.image.toDrive(compositeimage,
                                                         description='driveExportTask', 
                                                         folder = 'EarthEngineImages',
                                                         fileNamePrefix=gdexportname,scale=gdexportscale,maxPixels=1e9)                
                
                gdexportid = str(gdexport.id)
                print >> sys.stderr, '****Exporting to Google Drive, task id: %s '%gdexportid
                gdexport.start() 
            else:
                gdexportid = 'none'
#              --------------------------------------------------                                        
            downloadpathclip =  compositeimage.getDownloadUrl({'scale':10})                 
            if (polarization1 == 'VV') or (polarization1 == 'VV,VH'): 
                mapid = image1.select('VV').getMapId({'min': 0, 'max':1, 'opacity': 0.6}) 
                mapidclip = image1clip.select('VV').getMapId({'min': 0, 'max':1, 'opacity': 0.7})     
            else:
                mapid = image1.select('VH').getMapId({'min': 0, 'max':1, 'opacity': 0.6})                     
                mapidclip = image1clip.select('VH').getMapId({'min': 0, 'max':1, 'opacity': 0.7})                                            
            return render_template('sentinel1out.html',
                                          mapidclip = mapidclip['mapid'], 
                                          tokenclip = mapidclip['token'], 
                                          mapid = mapid['mapid'], 
                                          token = mapid['token'], 
                                          centerlon = centerlon,
                                          centerlat = centerlat,
                                          downloadtext = 'Download image collection intersection',
                                          downloadpath = downloadpath, 
                                          downloadpathclip = downloadpathclip, 
                                          projection = projection,
                                          systemid = systemid,
                                          count = count,
                                          timestamp = timestamp,
                                          gdexportid = gdexportid,
                                          timestamps = timestamps,
                                          systemids = systemids,
                                          polarization = polarization1,
                                          relativeorbitnumbers = relativeorbitnumbers)  
        except Exception as e:
            return '<br />An error occurred in Sentinel1: %s'%e
                  

@app.route('/sentinel2.html', methods = ['GET', 'POST'])
def Sentinel2():
    global msg, centerlon, centerlat, local
    if request.method == 'GET':
        if local:
            return render_template('sentinel2.html', msg = msg,
                                                     centerlon = centerlon,
                                                     centerlat = centerlat)
        else:
            return render_template('sentinel2web.html', msg = msg,
                                                     centerlon = centerlon,
                                                     centerlat = centerlat)
    else:
        try:
            startdate = request.form['startdate']  
            enddate = request.form['enddate']
            desired_projection = request.form['projection']
            minLat = float(request.form['minLat'])
            minLon = float(request.form['minLon'])
            maxLat = float(request.form['maxLat'])
            maxLon = float(request.form['maxLon'])
            if request.form.has_key('export'):        
                export = request.form['export']
            else:
                export = ' '
            gdexportname = request.form['exportname'] 
            gdexportscale = float(request.form['gdexportscale'])           
            start = ee.Date(startdate)
            finish = ee.Date(enddate)    
            
            rect = ee.Geometry.Rectangle(minLon,minLat,maxLon,maxLat)     
            centerlon = (minLon + maxLon)/2.0
            centerlat = (minLat + maxLat)/2.0 
            ulPoint = ee.Geometry.Point([minLon,maxLat])   
            lrPoint = ee.Geometry.Point([maxLon,minLat]) 
            collection = ee.ImageCollection('COPERNICUS/S2') \
                        .filterBounds(ulPoint) \
                        .filterBounds(lrPoint) \
                        .filterDate(start, finish) \
                        .sort('CLOUD_COVERAGE_ASSESSMENT', True) 
            count = collection.toList(100).length().getInfo()    
            if count==0:
                raise ValueError('No images found')        
            image = ee.Image(collection.first())         
            imageclip = image.clip(rect)              
            timestamp = ee.Date(image.get('system:time_start')).getInfo()
            timestamp = time.gmtime(int(timestamp['value'])/1000)
            timestamp = time.strftime('%c', timestamp)
            systemid = image.get('system:id').getInfo()
            cloudcover = image.get('CLOUD_COVERAGE_ASSESSMENT').getInfo()
            projection = image.select('B2').projection().getInfo()['crs']
            if desired_projection != 'default':
                projection = desired_projection     
            downloadpath = image.getDownloadUrl({'scale':30,'crs':projection})    
            if export == 'export':
#              export to Google Drive --------------------------
                gdexport = ee.batch.Export.image.toDrive(imageclip.select('B2','B3','B4','B8'),
                                         description='driveExportTask', 
                                         folder = 'EarthEngineImages',
                                         fileNamePrefix=gdexportname,scale=gdexportscale,maxPixels=1e9) 
                
                
                gdexportid = str(gdexport.id)
                print >> sys.stderr, '****Exporting to Google Drive, task id: %s '%gdexportid
                gdexport.start() 
            else:
                gdexportid = 'none'
#              --------------------------------------------------                    
            downloadpathclip = imageclip.select('B2','B3','B4','B8').getDownloadUrl({'scale':10, 'crs':projection})
            rgb = image.select('B2','B3','B4')            
            rgbclip = imageclip.select('B2','B3','B5')                 
            mapid = rgb.getMapId({'min':0, 'max':2000, 'opacity': 0.6}) 
            mapidclip = rgbclip.getMapId({'min':0, 'max':2000, 'opacity': 1.0})          
            return render_template('sentinel2out.html',
                                          mapidclip = mapidclip['mapid'], 
                                          tokenclip = mapidclip['token'], 
                                          mapid = mapid['mapid'], 
                                          token = mapid['token'], 
                                          centerlon = centerlon,
                                          centerlat = centerlat,
                                          downloadtext = 'Download image intersection',
                                          downloadpath = downloadpath, 
                                          downloadpathclip = downloadpathclip, 
                                          projection = projection,
                                          systemid = systemid,
                                          cloudcover = cloudcover,
                                          count = count,
                                          timestamp = timestamp)  
        except Exception as e:
            return '<br />An error occurred in Sentinel2: %s'%e  
        
@app.route('/mad.html', methods = ['GET', 'POST'])
def Mad():
    global local
    if request.method == 'GET':
        return render_template('mad.html', msg = msg)  
    else:
        if not local:
            return 'not yet implemented'
        try:
            niter = int(request.form['iterations'])
            start1 = ee.Date(request.form['startdate1'])
            finish1 = ee.Date(request.form['enddate1'])
            start2 = ee.Date(request.form['startdate2'])
            finish2 = ee.Date(request.form['enddate2'])   
            minLat = float(request.form['minLat'])
            minLon = float(request.form['minLon'])
            maxLat = float(request.form['maxLat'])
            maxLon = float(request.form['maxLon'])
            gdexportname = request.form['exportname']               
            if request.form.has_key('export'):        
                export = request.form['export']
            else:
                export = ' '                            
            rect = ee.Geometry.Rectangle(minLon,minLat,maxLon,maxLat)     
            centerlon = (minLon + maxLon)/2.0
            centerlat = (minLat + maxLat)/2.0 
            ulPoint = ee.Geometry.Point([minLon,maxLat])   
            lrPoint = ee.Geometry.Point([maxLon,minLat]) 
            collection = ee.ImageCollection('LT5_L1T') \
                        .filterBounds(ulPoint) \
                        .filterBounds(lrPoint) \
                        .filterDate(start1, finish1) \
                        .sort('CLOUD_COVER', True) 
            count = collection.toList(100).length().getInfo()    
            if count==0:
                raise ValueError('No images found for first time interval')        
            image1 = ee.Image(collection.first()).clip(rect).select('B1','B2','B3','B4','B5','B7')               
            timestamp1 = ee.Date(image1.get('system:time_start')).getInfo()
            timestamp1 = time.gmtime(int(timestamp1['value'])/1000)
            timestamp1 = time.strftime('%c', timestamp1) 
            systemid1 = image1.get('system:id').getInfo()
            cloudcover1 = image1.get('CLOUD_COVER').getInfo()
            collection = ee.ImageCollection('LT5_L1T') \
                        .filterBounds(ulPoint) \
                        .filterBounds(lrPoint) \
                        .filterDate(start2, finish2) \
                        .sort('CLOUD_COVER', True) 
            count = collection.toList(100).length().getInfo()    
            if count==0:
                raise ValueError('No images found for second time interval')        
            image2 = ee.Image(collection.first()).clip(rect).select('B1','B2','B3','B4','B5','B7') 
            timestamp2 = ee.Date(image2.get('system:time_start')).getInfo()
            timestamp2 = time.gmtime(int(timestamp2['value'])/1000)
            timestamp2 = time.strftime('%c', timestamp2) 
            systemid2 = image2.get('system:id').getInfo()  
            cloudcover2 = image2.get('CLOUD_COVER').getInfo()                                                  
#          iMAD:
            B1 = image1.bandNames().get(0)
            input_dict = ee.Dictionary({'image1':image1,'image2':image2}) 
            first = ee.Dictionary({'weights':image1.select(ee.String(B1)).multiply(0).add(ee.Image.constant(1)),
                                   'MAD':ee.Image.constant(0)})
#          iteration not yet possible, but this is how it goes:   
#            result = ee.List.repeat(input_dict, nMax).iterate(imad,first)
#          fake iteration:                   
            itr = 0
            while itr < niter: 
                result = imad(input_dict,first) 
                weights = result.get('weights')
                first = ee.Dictionary({'weights':weights,'MAD':ee.Image.constant(0)}) 
                itr += 1    
#          ---------------           
            MAD = ee.Image(result.get('MAD'))
            bNames = MAD.bandNames() 
            nBands = len(bNames.getInfo())
            lastMAD = ee.String(MAD.bandNames().get(nBands-1))          
            scale = image1.select(ee.String(B1)).projection().nominalScale().getInfo() 
            downloadpath = MAD.getDownloadUrl({'scale':scale, 'crs':'EPSG:4326'})                    
            mapid = MAD.select(lastMAD).getMapId({'min': -20, 'max': 20, 'opacity': 0.7})      
            if export == 'export':
#              export to Google Drive --------------------------
                gdexport = ee.batch.Export.image.toDrive(MAD,
                                                         description='driveExportTask', 
                                                         folder = 'EarthEngineImages',
                                                         fileNamePrefix=gdexportname,scale=scale,maxPixels=1e9)
                
                
                gdexportid = str(gdexport.id)
                print '****Exporting to Google Drive, task id: %s '%gdexportid
                gdexport.start() 
            else:
                gdexportid = 'none'
#              --------------------------------------------------                                 
            return render_template('madout.html',
                                          mapid = mapid['mapid'], 
                                          token = mapid['token'], 
                                          centerlon = centerlon,
                                          centerlat = centerlat,
                                          downloadpath = downloadpath, 
                                          systemid1 = systemid1,
                                          systemid2 = systemid2,
                                          cloudcover1 = cloudcover1,
                                          cloudcover2 = cloudcover2,
                                          timestamp1 = timestamp1,
                                          timestamp2 = timestamp2)  
        except Exception as e:
            return '<br />An error occurred in MAD: %s'%e        
        
@app.route('/wishart.html', methods = ['GET', 'POST'])
def Wishart():
    global msg, centerlon, centerlat, local
    if request.method == 'GET':
        if local:
            return render_template('wishart.html', msg = msg,
                                                     centerlon = centerlon,
                                                     centerlat = centerlat)
        else:
            return render_template('wishartweb.html', msg = msg,
                                                     centerlon = centerlon,
                                                     centerlat = centerlat)
    else:      
        try:
            start1 = ee.Date(request.form['startdate1'])
            finish1 = ee.Date(request.form['enddate1'])
            start2 = ee.Date(request.form['startdate2'])
            finish2 = ee.Date(request.form['enddate2'])   
            minLat = float(request.form['minLat'])
            minLon = float(request.form['minLon'])
            maxLat = float(request.form['maxLat'])
            maxLon = float(request.form['maxLon'])
            orbit = request.form['orbit']
            polarization1 = request.form['polarization']
            relativeorbitnumber = request.form['relativeorbitnumber']
            significance = float(request.form['significance'])
            if polarization1 == 'VV,VH':
                polarization = ['VV','VH']
            else:
                polarization = polarization1
            exportname = request.form['exportname'] 
            assexportscale = float(request.form['assexportscale'])               
            if request.form.has_key('export'):        
                export = request.form['export']
            else:
                export = ' ' 
            if request.form.has_key('median'):        
                median = True
            else:
                median = False
            rect = ee.Geometry.Rectangle(minLon,minLat,maxLon,maxLat)     
            centerlon = (minLon + maxLon)/2.0
            centerlat = (minLat + maxLat)/2.0 
            ulPoint = ee.Geometry.Point([minLon,maxLat])   
            lrPoint = ee.Geometry.Point([maxLon,minLat])     
#          get the first time point image           
            collection = ee.ImageCollection('COPERNICUS/S1_GRD') \
                        .filterBounds(ulPoint) \
                        .filterBounds(lrPoint) \
                        .filterDate(start1, finish1) \
                        .filter(ee.Filter.eq('transmitterReceiverPolarisation', polarization)) \
                        .filter(ee.Filter.eq('resolution_meters', 10)) \
                        .filter(ee.Filter.eq('instrumentMode', 'IW')) \
                        .filter(ee.Filter.eq('orbitProperties_pass', orbit)) 
            if relativeorbitnumber != '':
                collection = collection.filter(ee.Filter.eq('relativeOrbitNumber_start', int(relativeorbitnumber))) 
            count = collection.toList(100).length().getInfo()    
            if count==0:
                raise ValueError('No images found for first time interval')     
            collection = collection.sort('system:time_start')       
            image1 = ee.Image(collection.first()).clip(rect)   
            timestamp1 = ee.Date(image1.get('system:time_start')).getInfo()
            timestamp1= time.gmtime(int(timestamp1['value'])/1000)
            timestamp1 = time.strftime('%c', timestamp1) 
            systemid1 = image1.get('system:id').getInfo()   
            relativeOrbitNumber1 = int(image1.get('relativeOrbitNumber_start').getInfo())
#          get the second time point image           
            collection = ee.ImageCollection('COPERNICUS/S1_GRD') \
                        .filterBounds(ulPoint) \
                        .filterBounds(lrPoint) \
                        .filterDate(start2, finish2) \
                        .filter(ee.Filter.eq('transmitterReceiverPolarisation', polarization)) \
                        .filter(ee.Filter.eq('resolution_meters', 10)) \
                        .filter(ee.Filter.eq('instrumentMode', 'IW')) \
                        .filter(ee.Filter.eq('orbitProperties_pass', orbit)) 
            if relativeorbitnumber != '':
                collection = collection.filter(ee.Filter.eq('relativeOrbitNumber_start', int(relativeorbitnumber))) 
            count = collection.toList(100).length().getInfo()    
            if count==0:
                raise ValueError('No images found for second time interval')      
            collection = collection.sort('system:time_start')       
            image2 = ee.Image(collection.first()).clip(rect)                    
            timestamp2 = ee.Date(image2.get('system:time_start')).getInfo()
            timestamp2= time.gmtime(int(timestamp2['value'])/1000)
            timestamp2 = time.strftime('%c', timestamp2) 
            systemid2 = image2.get('system:id').getInfo()   
            relativeOrbitNumber2 = int(image2.get('relativeOrbitNumber_start').getInfo())
#          Wishart change detection    
            if polarization1=='VV,VH':
                image1 = get_vvvh(image1)
                image2 = get_vvvh(image2) 
            elif polarization1=='VV':
                image1 = get_vv(image1)
                image2 = get_vv(image2)   
            else:
                image1 = get_vh(image1)
                image2 = get_vh(image2) 
            
            result = ee.Dictionary(omnibus(ee.List([image1,image2]),significance,median))
            cmap = ee.Image(result.get('cmap'))   
            
            mapid = cmap.getMapId({'min':0, 'max':1 ,'palette':'black,red', 'opacity':0.4})
            downloadpath = cmap.getDownloadUrl({'scale':10})
            
            if export == 'export':
#              export to Assets ---------------------------------
                assexport = ee.batch.Export.image.toAsset(cmap,description="wishartTask", 
                                                          assetId=exportname,scale=assexportscale,maxPixels=1e9)
                assexportid = str(assexport.id)
                print '****Exporting to Assets, task id: %s '%assexportid
                assexport.start() 
            else:
                assexportid = 'none'
#              --------------------------------------------------               

            return render_template('wishartout.html',
                                      mapid = mapid['mapid'], 
                                      token = mapid['token'], 
                                      centerlon = centerlon,
                                      centerlat = centerlat,
                                      downloadpath = downloadpath, 
                                      systemid1 = systemid1,
                                      systemid2 = systemid2,
                                      timestamp1 = timestamp1,
                                      timestamp2 = timestamp2,
                                      relativeOrbitNumber1 = relativeOrbitNumber1,
                                      relativeOrbitNumber2 = relativeOrbitNumber2,
                                      significance = significance,
                                      polarization = polarization1,
                                      assexportid = assexportid)
                
        except Exception as e:
            return '<br />An error occurred in wishart: %s'%e    
        
@app.route('/omnibus.html', methods = ['GET', 'POST'])
def Omnibus():       
    global msg, centerlon, centerlat, jet, local
    if request.method == 'GET':
        if local:
            return render_template('omnibus.html', msg = msg,
                                                     centerlon = centerlon,
                                                     centerlat = centerlat)
        else:
            return render_template('omnibusweb.html', msg = msg,
                                                     centerlon = centerlon,
                                                     centerlat = centerlat)            
    else:
        try: 
            startdate = request.form['startdate']  
            enddate = request.form['enddate']  
            orbit = request.form['orbit']
            polarization1 = request.form['polarization']
            relativeorbitnumber = request.form['relativeorbitnumber']
            if polarization1 == 'VV,VH':
                polarization = ['VV','VH']
            else:
                polarization = polarization1
            significance = float(request.form['significance'])                
            mode = request.form['mode']          
            minLat = float(request.form['minLat'])
            minLon = float(request.form['minLon'])
            maxLat = float(request.form['maxLat'])
            maxLon = float(request.form['maxLon'])  
            assexportscale = float(request.form['assexportscale'])
            gdexportscale = float(request.form['gdexportscale'])
            if request.form.has_key('assexport'):        
                assexport = request.form['assexport']
            else:
                assexport = 'none'
            if request.form.has_key('gdexport'):        
                gdexport = request.form['gdexport']
            else:
                gdexport = 'none'    
            if request.form.has_key('median'):        
                median = True
            else:
                median = False                
            assexportname = request.form['assexportname']
            gdexportname = request.form['gdexportname']
            start = ee.Date(startdate)
            finish = ee.Date(enddate)            
            rect = ee.Geometry.Rectangle(minLon,minLat,maxLon,maxLat)     
            centerlon = (minLon + maxLon)/2.0
            centerlat = (minLat + maxLat)/2.0 
            ulPoint = ee.Geometry.Point([minLon,maxLat])   
            lrPoint = ee.Geometry.Point([maxLon,minLat])                
            collection = ee.ImageCollection('COPERNICUS/S1_GRD') \
                        .filterBounds(ulPoint) \
                        .filterBounds(lrPoint) \
                        .filterDate(start, finish) \
                        .filter(ee.Filter.eq('transmitterReceiverPolarisation', polarization)) \
                        .filter(ee.Filter.eq('resolution_meters', 10)) \
                        .filter(ee.Filter.eq('instrumentMode', mode)) \
                        .filter(ee.Filter.eq('orbitProperties_pass', orbit)) 
            if relativeorbitnumber != '':
                collection = collection.filter(ee.Filter.eq('relativeOrbitNumber_start', int(relativeorbitnumber))) 
            collection = collection.sort('system:time_start')                                     
            acquisition_times = ee.List(collection.aggregate_array('system:time_start'))                                           
            count = acquisition_times.length().getInfo() 
            if count==0:
                raise ValueError('No images found')   
            timestamplist = []
            for timestamp in acquisition_times.getInfo():
                tmp = time.gmtime(int(timestamp)/1000)
                timestamplist.append(time.strftime('%c', tmp))               
            timestamp = timestamplist[0]    
            timestamps = str(timestamplist)    
            relative_orbit_numbers = ee.List(collection.aggregate_array('relativeOrbitNumber_start'))             
            relativeorbitnumberlist = []
            for ron  in relative_orbit_numbers.getInfo():
                relativeorbitnumberlist.append(ron)
            relativeorbitnumbers = str(relativeorbitnumberlist)                                        
            image = ee.Image(collection.first())                       
            systemid = image.get('system:id').getInfo()   
            if (polarization1 == 'VV') or (polarization1 == 'VV,VH'): 
                projection = image.select('VV').projection().getInfo()['crs']
            else:
                projection = image.select('VH').projection().getInfo()['crs'] 
#          make into collection of VV, VH or VVVH images and restore linear scale             
            if polarization == 'VV':
                pcollection = collection.map(get_vv)
            elif polarization == 'VH':
                pcollection = collection.map(get_vh)
            else:
                pcollection = collection.map(get_vvvh) 
#          get the list of images and clip to roi
            pList = pcollection.toList(count)   
            first = ee.Dictionary({'imlist':ee.List([]),'rect':rect}) 
            imList = ee.Dictionary(pList.iterate(clipList,first)).get('imlist')  
#          run the algorithm            
            result = ee.Dictionary(omnibus(imList,significance,median))
            cmap = ee.Image(result.get('cmap'))   
            smap = ee.Image(result.get('smap'))
            fmap = ee.Image(result.get('fmap'))  
            bmap = ee.Image(result.get('bmap'))
            bmapbands = ['b0%i'%i for i in range(1,10)]+['b%i'%i for i in range(10,100)]
            bands = ['cmap','smap','fmap']+bmapbands[0:count-1]
            cmaps = ee.Image.cat(cmap,smap,fmap,bmap).byte().rename(bands)           
            if assexport == 'assexport':
#              export to Assets 
                assexport = ee.batch.Export.image.toAsset(cmaps,
                                                          description='assetExportTask', 
                                                          assetId=assexportname,scale=assexportscale,maxPixels=1e9)
                assexportid = str(assexport.id)
                print '****Exporting to Assets, task id: %s '%assexportid
                assexport.start() 
            else:
                assexportid = 'none'                
            if gdexport == 'gdexport':
#              export to Drive 
                gdexport = ee.batch.Export.image.toDrive(cmaps,
                                                         description='driveExportTask', 
                                                         folder = 'EarthEngineImages',
                                                         fileNamePrefix=gdexportname,scale=gdexportscale,maxPixels=1e9)
                gdexportid = str(gdexport.id)
                print '****Exporting to Google Drive, task id: %s '%gdexportid
                gdexport.start() 
            else:
                gdexportid = 'none'                                      
            fmapid = fmap.getMapId({'min': 0, 'max':count/2,'palette':jet, 'opacity': 0.4}) 
            return render_template('omnibusout.html',
                                          mapid = fmapid['mapid'], 
                                          token = fmapid['token'], 
                                          centerlon = centerlon,
                                          centerlat = centerlat,
                                          projection = projection,
                                          systemid = systemid,
                                          count = count,
                                          timestamp = timestamp,
                                          assexportid = 'none',
                                          gdexportid = 'none',
                                          timestamps = timestamps,
                                          polarization = polarization1,
                                          relativeorbitnumbers = relativeorbitnumbers)                  
                            
        except Exception as e:
            return '<br />An error occurred in omnibus: %s'%e    
                                        
if __name__ == '__main__':
    
    app.run(debug=True, host='0.0.0.0')
  