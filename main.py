import numpy as np
import cv2 as cv
from collections import deque

def setValues(x):
    print("")

cv.namedWindow("Color detectors")

cv.createTrackbar("Upper Hue", "Color detectors", 136, 180, setValues)
cv.createTrackbar("Upper Saturation", "Color detectors", 255, 255, setValues)
cv.createTrackbar("Upper Value", "Color detectors", 255, 255, setValues)

cv.createTrackbar("Lower Hue", "Color detectors", 100, 180, setValues)
cv.createTrackbar("Lower Saturation", "Color detectors", 83, 255, setValues)
cv.createTrackbar("Lower Value", "Color detectors", 84, 255, setValues)

bpoints = [deque(maxlen=1024)]
gpoints = [deque(maxlen=1024)]
rpoints = [deque(maxlen=1024)]
ypoints = [deque(maxlen=1024)]

blue_index = 0
green_index = 0
red_index = 0
yellow_index = 0

kernel = np.ones((5,5),np.uint8)


colors = [(255,0,0), (0,255,0), (0,0,255), (0,255,255)]
colorIndex = 0

paintWindow = np.zeros((480,640,3), dtype=np.uint8) + 255


paintWindow = cv.rectangle(paintWindow,(40,1),(140,65),(0,0,0), -1)
paintWindow = cv.rectangle(paintWindow,(160,1),(255,65),colors[0],-1)
paintWindow = cv.rectangle(paintWindow,(275,1),(370,65),colors[1],-1)
paintWindow = cv.rectangle(paintWindow,(390,1),(485,65),colors[2],-1)
paintWindow = cv.rectangle(paintWindow,(505,1),(600,65),colors[3],-1)

cv.putText(paintWindow,"CLEAR",(54,33), cv.FONT_HERSHEY_SIMPLEX, 0.5,(255,255,255),2, cv.LINE_AA)

# cv.namedWindow('Paint',cv.WINDOW_AUTOSIZE)

cap = cv.VideoCapture(0)
cv.namedWindow("Live Drawing", cv.WINDOW_NORMAL)
cv.resizeWindow("Live Drawing", 1280, 720)


while True:
    Success, frame = cap.read()
    if not Success:
        break

    frame = cv.flip(frame,1)
    hsv = cv.cvtColor(frame,cv.COLOR_BGR2HSV)

    u_hue = cv.getTrackbarPos("Upper Hue", "Color detectors")
    u_saturation = cv.getTrackbarPos("Upper Saturation", "Color detectors")
    u_value = cv.getTrackbarPos("Upper Value", "Color detectors")  

    l_hue = cv.getTrackbarPos("Lower Hue", "Color detectors")
    l_saturation = cv.getTrackbarPos("Lower Saturation", "Color detectors")
    l_value = cv.getTrackbarPos("Lower Value", "Color detectors")  

    Upper_hsv = np.array([u_hue, u_saturation, u_value])
    Lower_hsv = np.array([l_hue, l_saturation, l_value])

    frame = cv.rectangle(frame,(40,1), (140,65), (0,0,0), -1)
    frame = cv.rectangle(frame,(160,1),(255,65),colors[0],-1)
    frame = cv.rectangle(frame,(275,1),(370,65),colors[1],-1)
    frame = cv.rectangle(frame,(390,1),(485,65),colors[2],-1)
    frame = cv.rectangle(frame,(505,1),(600,65),colors[3],-1)

    cv.putText(frame,"CLEAR",(54,33), cv.FONT_HERSHEY_SIMPLEX, 0.5,(255,255,255),2, cv.LINE_AA)

    mask = cv.inRange(hsv, Lower_hsv, Upper_hsv)
    mask = cv.erode(mask, kernel, iterations=1)
    mask = cv.morphologyEx(mask, cv.MORPH_OPEN, kernel)
    mask = cv.dilate(mask, kernel, iterations=1)

    cnts , z = cv.findContours(mask.copy(), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)

    center = None

    if len(cnts) > 0:
        cnt = sorted(cnts, key=cv.contourArea, reverse=True)[0]
        ((x,y), radius) = cv.minEnclosingCircle(cnt)
        cv.circle(frame, ((int(x),int(y))), int(radius), (0,255,255), 2)
        M = cv.moments(cnt)

        if M["m00"] != 0:
            center = (int(M['m10']/ M['m00']), int(M['m01']/ M['m00']))

        if center[1] <= 65:
            if 40 <= center[0] <= 140:               
                bpoints = [deque(maxlen=512)]
                gpoints = [deque(maxlen=512)]
                rpoints = [deque(maxlen=512)]
                ypoints = [deque(maxlen=512)]

                blue_index = 0
                green_index = 0
                red_index = 0
                yellow_index = 0
                paintWindow[67:,:,:] = 255
            elif 160 <= center[0] <= 255:
                colorIndex = 0 # blue
            elif 275 <= center[0] <= 370:
                colorIndex = 1 # green
            elif 390 <= center[0] <= 485:
                colorIndex = 2 # red
            elif 505 <= center[0] <= 600:
                colorIndex = 3 # yellow
        else:
                if colorIndex == 0:
                    bpoints[blue_index].appendleft(center)
                elif colorIndex == 1:
                    gpoints[green_index].appendleft(center)
                elif colorIndex == 2:
                    rpoints[red_index].appendleft(center)
                elif colorIndex == 3:
                    ypoints[yellow_index].appendleft(center)
    else:
        bpoints.append(deque(maxlen=512))
        blue_index += 1
        gpoints.append(deque(maxlen=512))
        green_index += 1
        rpoints.append(deque(maxlen=512))
        red_index += 1
        ypoints.append(deque(maxlen=512))
        yellow_index += 1

    points = [bpoints,gpoints,rpoints,ypoints]
    for i in range(len(points)):
        for j in range(len(points[i])):
            for k in range(1,len(points[i][j])):
                if points[i][j][k-1] is None or points[i][j][k] is None:
                    continue
                cv.line(frame,points[i][j][k-1],points[i][j][k],colors[i],2)
                cv.line(paintWindow,points[i][j][k-1],points[i][j][k],colors[i],2)

    cv.imshow("Live Drawing", frame)
    cv.imshow("Paint", paintWindow)
    cv.imshow("Mask", mask)




    if cv.waitKey(1) & 0xff == ord('q'):
        break

cap.release()
cv.destroyAllWindows()
